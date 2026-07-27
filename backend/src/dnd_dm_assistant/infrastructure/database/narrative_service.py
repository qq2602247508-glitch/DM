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
                successes = operation.get("successes", 0)
                failures = operation.get("failures", 0)
                outcome = (
                    "success"
                    if successes > failures
                    else "complication" if failures else "pending"
                )
                rows.append(
                    {
                        "kind": kind,
                        "before": {},
                        "after": {
                            "mode": mode,
                            "successes": successes,
                            "failures": failures,
                            "outcome": outcome,
                        },
                        "explanation": f"{mode}：成功 {successes} / 失败 {failures}",
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
                            title=f"{row['after']['mode']} 结算",
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
