from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Character,
    DowntimeActivity,
    Event,
    FactionReputation,
    OperationTransaction,
    Quest,
    QuestObjective,
    StoryBeat,
)

MODELS: dict[str, Any] = {
    "story_beat": StoryBeat,
    "quest_objective": QuestObjective,
    "reputation": FactionReputation,
    "downtime": DowntimeActivity,
    "quest_reward": Quest,
}


class NarrativeService:
    """A preview/confirm boundary for narrative state; previews never write."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _token(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def _preview(
        self, session: Session, campaign_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        if session.get(Campaign, campaign_id) is None:
            raise StateNotFoundError("campaign not found")
        rows: list[dict[str, Any]] = []
        for operation in request["operations"]:
            kind = operation["kind"]
            if kind == "runtime":
                mode = operation.get("mode") or "skill_challenge"
                runtime_id = operation.get("runtime_id")
                before = self._runtime_state(session, campaign_id, runtime_id)
                successes = int(before.get("successes", 0)) + int(
                    operation.get("success_delta") or operation.get("successes") or 0
                )
                failures = int(before.get("failures", 0)) + int(
                    operation.get("failure_delta") or operation.get("failures") or 0
                )
                target_successes = int(
                    operation.get("target_successes")
                    or before.get("target_successes")
                    or 3
                )
                target_failures = int(
                    operation.get("target_failures")
                    or before.get("target_failures")
                    or 3
                )
                status = (
                    "succeeded"
                    if successes >= target_successes
                    else "failed"
                    if failures >= target_failures
                    else "active"
                )
                after = {
                    "runtime_id": runtime_id,
                    "title": operation.get("title") or before.get("title") or mode,
                    "detail": operation.get("detail") or before.get("detail"),
                    "mode": mode if not before else before.get("mode", mode),
                    "successes": successes,
                    "failures": failures,
                    "target_successes": target_successes,
                    "target_failures": target_failures,
                    "status": status,
                    "revision": int(before.get("revision", 0)) + 1,
                }
                rows.append(
                    {
                        "kind": kind,
                        "before": before,
                        "after": after,
                        "explanation": (
                            f"{after['title']}：成功 {successes}/{target_successes}，"
                            f"失败 {failures}/{target_failures}（{status}）"
                        ),
                    }
                )
                continue
            model = MODELS[kind]
            entity = session.get(model, operation.get("entity_id"))
            if entity is None or entity.campaign_id != campaign_id:
                raise StateNotFoundError(f"{kind} not found in campaign")
            before = serialize(entity)
            after = dict(before)
            if operation.get("status") is not None:
                after["status"] = operation["status"]
            if kind == "reputation" and operation.get("score_delta") is not None:
                after["score"] = int(before["score"]) + int(operation["score_delta"])
            if kind == "downtime" and operation.get("progress_days") is not None:
                progress = int(before["progress_days"]) + int(operation["progress_days"])
                after["progress_days"] = min(int(before["duration_days"]), progress)
                if after["progress_days"] >= int(before["duration_days"]):
                    after["status"] = "completed"
            if kind == "quest_reward":
                if before.get("xp_awarded"):
                    raise ValueError("quest XP has already been awarded")
                if not operation.get("character_ids"):
                    raise ValueError("quest reward needs at least one character")
                after["xp_awarded"] = True
            xp_each = operation.get("xp_each")
            if xp_each is None and kind == "quest_reward":
                xp_each = before.get("xp_reward", 0)
            rows.append(
                {
                    "kind": kind,
                    "entity_id": entity.id,
                    "version": entity.version,
                    "before": before,
                    "after": after,
                    "character_ids": operation.get("character_ids", []),
                    "xp_each": xp_each,
                }
            )
        payload = {
            "campaign_id": campaign_id,
            "operations": request["operations"],
            "rows": rows,
            "notes": request.get("notes"),
        }
        return {
            **payload,
            "preview_token": self._token(payload),
            "warnings": ["预览不会写入；确认后所有条目会作为一个事务提交。"],
        }

    @staticmethod
    def _runtime_state(
        session: Session, campaign_id: str, runtime_id: str | None
    ) -> dict[str, Any]:
        if not runtime_id:
            return {}
        candidates = session.scalars(
            select(Event)
            .where(
                Event.campaign_id == campaign_id,
                Event.event_type == "narrative_runtime",
            )
            .order_by(Event.created_at.desc(), Event.id.desc())
        ).all()
        matches: list[dict[str, Any]] = []
        for candidate in candidates:
            metadata = candidate.metadata_json or {}
            if metadata.get("runtime_id") == runtime_id:
                matches.append(dict(metadata))
        return max(matches, key=lambda item: int(item.get("revision", 0)), default={})

    def list_runtimes(self, campaign_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            if session.get(Campaign, campaign_id) is None:
                raise StateNotFoundError("campaign not found")
            events = session.scalars(
                select(Event)
                .where(
                    Event.campaign_id == campaign_id,
                    Event.event_type == "narrative_runtime",
                )
                .order_by(Event.created_at.desc(), Event.id.desc())
            ).all()
            latest: dict[str, dict[str, Any]] = {}
            for event in events:
                item = dict(event.metadata_json or {})
                runtime_id = str(item.get("runtime_id") or "")
                if not runtime_id:
                    continue
                current = latest.get(runtime_id)
                if current is None or int(str(item.get("revision", 0))) > int(
                    str(current.get("revision", 0))
                ):
                    latest[runtime_id] = {**item, "updated_at": event.created_at}
            return sorted(
                latest.values(),
                key=lambda item: str(item.get("updated_at") or ""),
                reverse=True,
            )

    def preview(self, campaign_id: str, request: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._preview(session, campaign_id, request)

    def confirm(self, campaign_id: str, request: dict[str, Any]) -> dict[str, Any]:
        token = request.get("preview_token")
        if not token:
            raise ValueError("preview_token is required")
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == request["idempotency_key"],
                )
            )
            if existing is not None:
                return {
                    "idempotent": True,
                    "transaction": serialize(existing),
                    "after": existing.after_snapshot,
                }
            body = {
                key: value
                for key, value in request.items()
                if key not in {"preview_token", "idempotency_key"}
            }
            preview = self._preview(session, campaign_id, body)
            if preview["preview_token"] != token:
                raise VersionConflict("narrative preview", "state", 1, 2)
            for row in preview["rows"]:
                if row["kind"] == "runtime":
                    session.add(
                        Event(
                            campaign_id=campaign_id,
                            event_type="narrative_runtime",
                            title=f"{row['after']['title']}推进",
                            description=row["explanation"],
                            visibility="dm",
                            metadata_json=row["after"],
                        )
                    )
                    continue
                entity = session.get(MODELS[row["kind"]], row["entity_id"])
                actual_version = 0 if entity is None else entity.version
                if actual_version != row["version"]:
                    raise VersionConflict(
                        row["kind"], row["entity_id"], row["version"], actual_version
                    )
                if entity is None:
                    raise StateNotFoundError(f"{row['kind']} not found in campaign")
                after = row["after"]
                for field in ("status", "score", "progress_days", "xp_awarded"):
                    if field in after and getattr(entity, field, None) != after[field]:
                        setattr(entity, field, after[field])
                if row["kind"] == "quest_reward":
                    for character_id in row["character_ids"]:
                        character = session.get(Character, character_id)
                        if character is None or character.campaign_id != campaign_id:
                            raise StateNotFoundError("reward character not found")
                        character.experience += int(row["xp_each"] or 0)
                entity.version += 1
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="narrative_transaction",
                idempotency_key=request["idempotency_key"],
                status="applied",
                before_snapshot={"rows": [row["before"] for row in preview["rows"]]},
                after_snapshot={"rows": [row["after"] for row in preview["rows"]]},
                reason=request.get("notes"),
                source="game_table",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            return {
                "idempotent": False,
                "transaction": serialize(transaction),
                "after": transaction.after_snapshot,
            }
