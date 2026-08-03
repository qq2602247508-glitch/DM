from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.exploration import (
    movement_cost_ft,
    resolve_character_effect,
    resolve_chase_progress,
    resolve_downtime_progress,
    resolve_social_attitude,
    travel_minutes,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Character,
    CharacterCondition,
    Combat,
    Combatant,
    CurrencyTransaction,
    DowntimeActivity,
    Event,
    ExplorationTurn,
    Location,
    NPCMemory,
    OperationTransaction,
    Scene,
    SceneGrid,
    SceneObject,
    SceneToken,
    TravelLeg,
    Wallet,
    WorldClock,
)


class ExplorationService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def grid(self, campaign_id: str, scene_id: str) -> dict[str, Any]:
        with Session(self.engine) as s:
            self._scene(s, campaign_id, scene_id)
            grid = s.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
            if grid is None:
                raise StateNotFoundError("scene grid not found")
            return {
                "grid": serialize(grid),
                "tokens": [
                    serialize(x)
                    for x in s.scalars(select(SceneToken).where(SceneToken.scene_id == scene_id))
                ],
                "objects": [
                    serialize(x)
                    for x in s.scalars(select(SceneObject).where(SceneObject.scene_id == scene_id))
                ],
            }

    def create_grid(self, campaign_id: str, scene_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            self._scene(s, campaign_id, scene_id)
            if s.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id)):
                raise ValueError("scene already has a grid")
            row = SceneGrid(scene_id=scene_id, **data)
            s.add(row)
            s.flush()
            self._materialize_layer_cells(s, row)
            return serialize(row)

    @staticmethod
    def _materialize_layer_cells(session: Session, grid: SceneGrid) -> None:
        """Turn generated layer cells into public, queryable map objects.

        The DM renderer can understand the compact ``layers_json`` payload,
        while the player gateway intentionally exposes only normalized public
        objects. Materializing once here keeps both views on the same map
        without dozens of follow-up HTTP writes from the browser.
        """
        raw_cells = grid.layers_json.get("cells", [])
        if not isinstance(raw_cells, list):
            return
        kind_map: dict[str, tuple[str, dict[str, object]]] = {
            "wall": ("wall", {}),
            "door": ("door", {}),
            "cover": ("cover", {}),
            "object": ("furniture", {}),
            "water": ("terrain", {"difficult": True, "terrain_kind": "water"}),
            "difficult": ("terrain", {"difficult": True, "terrain_kind": "difficult"}),
        }
        seen: set[tuple[int, int]] = set()
        for cell in raw_cells[:500]:
            if not isinstance(cell, dict):
                continue
            materialized = kind_map.get(str(cell.get("kind", "")))
            if materialized is None:
                continue
            object_type, metadata = materialized
            try:
                row = int(cell["row"])
                col = int(cell["col"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (1 <= row <= grid.height and 1 <= col <= grid.width):
                continue
            if (row, col) in seen:
                continue
            seen.add((row, col))
            label = str(cell.get("label") or object_type)[:200]
            session.add(
                SceneObject(
                    scene_id=grid.scene_id,
                    object_type=object_type,
                    label=label,
                    row=row,
                    col=col,
                    state="closed" if object_type == "door" else "active",
                    visibility="public",
                    metadata_json={"generated_from": "layers_json", **metadata},
                )
            )

    def add_token(self, campaign_id: str, scene_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            grid = self._grid(s, campaign_id, scene_id)
            self._bounds(grid, int(data["row"]), int(data["col"]), int(data.get("size_cells", 1)))
            row = SceneToken(scene_id=scene_id, **data)
            s.add(row)
            s.flush()
            return serialize(row)

    def add_object(self, campaign_id: str, scene_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s, s.begin():
            grid = self._grid(s, campaign_id, scene_id)
            self._bounds(
                grid,
                int(data["row"]),
                int(data["col"]),
                max(int(data.get("width_cells", 1)), int(data.get("height_cells", 1))),
            )
            row = SceneObject(scene_id=scene_id, **data)
            s.add(row)
            s.flush()
            return serialize(row)

    def preview_exploration(
        self, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with Session(self.engine) as s:
            return {
                **self._exploration_preview(s, campaign_id, scene_id, payload),
                "requires_confirmation": True,
            }

    def confirm_exploration(
        self, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        clean = {k: v for k, v in payload.items() if k not in {"preview_token", "idempotency_key"}}
        with Session(self.engine) as s, s.begin():
            existing = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == payload["idempotency_key"],
                )
            )
            if existing:
                return {
                    **dict(existing.after_snapshot),
                    "idempotent_replay": True,
                    "operation_transaction_id": existing.id,
                }
            preview = self._exploration_preview(s, campaign_id, scene_id, clean)
            if payload["preview_token"] != preview["preview_token"]:
                raise VersionConflict("exploration preview", scene_id, 1, 2)
            result = preview["result"]
            before: dict[str, Any] = {}
            after: dict[str, Any] = {"result": result}
            if clean.get("action") == "move" and clean.get("token_id"):
                token = s.get(SceneToken, clean["token_id"])
                if token is None or token.scene_id != scene_id:
                    raise StateNotFoundError("scene token not found")
                before["token"] = serialize(token)
                end = clean["path"][-1]
                token.row, token.col = int(end[0]), int(end[1])
                token.version += 1
                after["token"] = serialize(token)
            if (
                clean.get("action") == "interact"
                and clean.get("object_id")
                and clean.get("object_state")
            ):
                obj = s.get(SceneObject, clean["object_id"])
                if obj is None or obj.scene_id != scene_id:
                    raise StateNotFoundError("scene object not found")
                before["object"] = serialize(obj)
                obj.state = clean["object_state"]
                obj.version += 1
                after["object"] = serialize(obj)
            campaign = self._campaign(s, campaign_id)
            before["world_clock"] = self._clock_state(s, campaign)
            after["world_clock"] = self._advance_world_time(
                s, campaign, int(clean["minutes"]), datetime.now(UTC)
            )
            after["world_time"] = after["world_clock"]["current_time"]
            tx = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="exploration_turn",
                idempotency_key=payload["idempotency_key"],
                before_snapshot=before,
                after_snapshot={},
                reason=clean.get("notes"),
                source="dm",
                confirmed_at=datetime.now(UTC),
            )
            s.add(tx)
            s.flush()
            s.add(
                ExplorationTurn(
                    campaign_id=campaign_id,
                    scene_id=scene_id,
                    transaction_id=tx.id,
                    minutes=int(clean["minutes"]),
                    action=clean["action"],
                    result_json=result,
                )
            )
            after["operation_transaction_id"] = tx.id
            tx.after_snapshot = after
            s.flush()
            return {**after, "idempotent_replay": False}

    def preview_travel(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s:
            return {
                **self._travel_preview(s, campaign_id, payload),
                "requires_confirmation": True,
            }

    def confirm_travel(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        clean = {k: v for k, v in payload.items() if k not in {"preview_token", "idempotency_key"}}
        with Session(self.engine) as s, s.begin():
            existing = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == payload["idempotency_key"],
                )
            )
            if existing:
                return {
                    **dict(existing.after_snapshot),
                    "idempotent_replay": True,
                    "operation_transaction_id": existing.id,
                }
            preview = self._travel_preview(s, campaign_id, clean)
            if payload["preview_token"] != preview["preview_token"]:
                raise VersionConflict("travel preview", campaign_id, 1, 2)
            campaign = self._campaign(s, campaign_id)
            duration = int(preview["duration_minutes"])
            now = datetime.now(UTC)
            before = {
                "location_id": campaign.current_location_id,
                "campaign": serialize(campaign),
                "world_clock": self._clock_state(s, campaign),
            }
            campaign.current_location_id = clean["to_location_id"]
            world_clock = self._advance_world_time(
                s, campaign, duration, now, update_campaign=False
            )
            campaign.version += 1
            campaign.updated_at = now
            after: dict[str, object] = {
                "location_id": campaign.current_location_id,
                "duration_minutes": duration,
                "world_time": world_clock["current_time"],
                "world_clock": world_clock,
            }
            tx = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="travel_leg",
                idempotency_key=payload["idempotency_key"],
                before_snapshot=before,
                after_snapshot={},
                reason=clean.get("notes"),
                source="dm",
                confirmed_at=now,
            )
            s.add(tx)
            s.flush()
            details: dict[str, object] = {"notes": clean.get("notes")}
            encounter = clean.get("encounter")
            if isinstance(encounter, dict):
                details["encounter"] = {
                    "title": encounter["title"],
                    "outcome": encounter["outcome"],
                    "summary": encounter["summary"],
                    "visibility": encounter["visibility"],
                }
            leg = TravelLeg(
                campaign_id=campaign_id,
                from_location_id=before["location_id"],
                to_location_id=clean["to_location_id"],
                transaction_id=tx.id,
                distance_miles=float(clean["distance_miles"]),
                pace=clean["pace"],
                duration_minutes=duration,
                details_json=details,
            )
            s.add(leg)
            s.flush()
            after["travel_leg"] = serialize(leg)
            if isinstance(encounter, dict):
                event = Event(
                    campaign_id=campaign_id,
                    event_type="travel_encounter",
                    title=str(encounter["title"]),
                    description=str(encounter["summary"]),
                    occurred_at=self._event_time(s, campaign, now),
                    location_id=campaign.current_location_id,
                    visibility=str(encounter["visibility"]),
                    metadata_json={
                        "travel_leg_id": leg.id,
                        "outcome": encounter["outcome"],
                        "distance_miles": float(clean["distance_miles"]),
                        "pace": clean["pace"],
                    },
                )
                s.add(event)
                s.flush()
                details["encounter"] = {**dict(details["encounter"]), "event_id": event.id}
                leg.details_json = details
                after["travel_leg"] = serialize(leg)
                after["travel_encounter"] = serialize(event)
            after["campaign"] = serialize(campaign)
            after["operation_transaction_id"] = tx.id
            tx.after_snapshot = after
            s.flush()
            return {**after, "idempotent_replay": False}

    def preview_social_interaction(
        self, campaign_id: str, npc_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            preview = self._social_preview(session, campaign_id, npc_id, payload)
            return {**preview, "requires_confirmation": True}

    def confirm_social_interaction(
        self, campaign_id: str, npc_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        clean = {
            key: value
            for key, value in payload.items()
            if key not in {"preview_token", "idempotency_key"}
        }
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == payload["idempotency_key"],
                )
            )
            if existing is not None:
                return {
                    **dict(existing.after_snapshot or {}),
                    "idempotent_replay": True,
                    "operation_transaction_id": existing.id,
                }

            preview = self._social_preview(session, campaign_id, npc_id, clean)
            if preview["preview_token"] != payload["preview_token"]:
                raise VersionConflict("social interaction preview", npc_id, 1, 2)

            campaign = self._campaign(session, campaign_id)
            npc = self._npc(session, campaign_id, npc_id)
            now = datetime.now(UTC)
            before = {
                "npc": serialize(npc),
                "world_time": preview["world_time"]["before"],
                "world_clock_paused": preview["world_time"]["paused"],
            }
            npc.attitude = str(preview["npc"]["attitude"]["after"])
            npc.version += 1
            npc.updated_at = now
            memory = NPCMemory(
                campaign_id=campaign_id,
                npc_id=npc.id,
                summary=str(clean["summary"]),
                memory_kind=str(clean["memory_kind"]),
                attitude_delta=int(preview["npc"]["attitude"]["effective_delta"]),
                tags=list(clean.get("tags") or []),
                secret=bool(clean.get("secret", False)),
            )
            session.add(memory)

            clock = self._advance_world_time(session, campaign, int(clean["minutes"]), now)
            session.flush()

            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="social_interaction",
                idempotency_key=payload["idempotency_key"],
                status="applied",
                before_snapshot=before,
                after_snapshot={},
                reason=str(clean["summary"]),
                source="dm",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            after = {
                "npc": serialize(npc),
                "npc_memory": serialize(memory),
                "world_time": clock["current_time"],
                "world_clock": clock,
                "world_clock_paused": bool(clock["paused"]),
                "minutes": int(clean["minutes"]),
                "outcome": str(clean["outcome"]),
                "operation_transaction_id": transaction.id,
            }
            transaction.after_snapshot = after
            session.flush()
            return {**after, "idempotent_replay": False}

    def list_chases(self, campaign_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            return [
                serialize(event)
                for event in session.scalars(
                    select(Event)
                    .where(
                        Event.campaign_id == campaign_id,
                        Event.event_type == "exploration_chase",
                    )
                    .order_by(Event.updated_at.desc(), Event.id)
                )
            ]

    def preview_chase(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            return {
                **self._chase_preview(session, campaign_id, payload),
                "requires_confirmation": True,
            }

    def confirm_chase(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        clean = {
            key: value
            for key, value in payload.items()
            if key not in {"preview_token", "idempotency_key"}
        }
        with Session(self.engine) as session, session.begin():
            existing = self._operation(session, campaign_id, payload["idempotency_key"])
            if existing is not None:
                return self._operation_replay(existing)
            preview = self._chase_preview(session, campaign_id, clean)
            if preview["preview_token"] != payload["preview_token"]:
                raise VersionConflict(
                    "chase preview", str(clean.get("chase_event_id") or campaign_id), 1, 2
                )
            campaign = self._campaign(session, campaign_id)
            event = self._chase_event(session, campaign_id, clean.get("chase_event_id"))
            now = datetime.now(UTC)
            before: dict[str, Any] = {
                "chase": serialize(event) if event is not None else None,
                "world_clock": self._clock_state(session, campaign),
            }
            clock = self._advance_world_time(session, campaign, int(clean["minutes"]), now)
            progress = dict(preview["chase"])
            metadata = {
                "successes": progress["successes"],
                "failures": progress["failures"],
                "target_successes": progress["target_successes"],
                "target_failures": progress["target_failures"],
                "status": progress["status"],
                "last_outcome": clean["outcome"],
                "last_summary": clean["summary"],
            }
            if event is None:
                event = Event(
                    campaign_id=campaign_id,
                    event_type="exploration_chase",
                    title=str(clean["title"]),
                    description=str(clean["summary"]),
                    occurred_at=self._event_time(session, campaign, now),
                    location_id=campaign.current_location_id,
                    visibility=str(clean["visibility"]),
                    metadata_json=metadata,
                )
                session.add(event)
            else:
                before["chase"] = serialize(event)
                event.title = str(clean["title"])
                event.description = str(clean["summary"])
                event.visibility = str(clean["visibility"])
                event.metadata_json = metadata
                event.version += 1
                event.updated_at = now
            session.flush()
            character_effects = self._apply_character_effects(
                session,
                campaign_id,
                list(clean.get("character_effects") or []),
                source=f"追逐：{event.title}",
                now=now,
                effect_kind="chase",
            )
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="exploration_chase",
                idempotency_key=payload["idempotency_key"],
                status="applied",
                before_snapshot=before,
                after_snapshot={},
                reason=str(clean["summary"]),
                source="dm",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            after = {
                "chase": serialize(event),
                "character_effects": character_effects,
                "world_clock": clock,
                "world_time": clock["current_time"],
                "minutes": int(clean["minutes"]),
                "operation_transaction_id": transaction.id,
            }
            transaction.after_snapshot = after
            session.flush()
            return {**after, "idempotent_replay": False}

    def _chase_preview(
        self, session: Session, campaign_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        event = self._chase_event(session, campaign_id, payload.get("chase_event_id"))
        if event is not None:
            expected = int(payload["chase_version"])
            if event.version != expected:
                raise VersionConflict("chase", event.id, expected, event.version)
            metadata = dict(event.metadata_json or {})
            successes = int(metadata.get("successes") or 0)
            failures = int(metadata.get("failures") or 0)
            target_successes = int(metadata.get("target_successes") or payload["target_successes"])
            target_failures = int(metadata.get("target_failures") or payload["target_failures"])
            if str(metadata.get("status") or "active") != "active":
                raise ValueError("该追逐已经结束；请新建追逐而非继续推进")
        else:
            successes = failures = 0
            target_successes = int(payload["target_successes"])
            target_failures = int(payload["target_failures"])
        progress = resolve_chase_progress(
            successes=successes,
            failures=failures,
            target_successes=target_successes,
            target_failures=target_failures,
            outcome=str(payload["outcome"]),
        )
        effects = self._preview_character_effects(
            session, campaign_id, list(payload.get("character_effects") or [])
        )
        world_time = self._world_time_preview(session, campaign, int(payload["minutes"]))
        token_payload = {
            "request": payload,
            "chase": serialize(event) if event is not None else None,
            "world_clock": self._clock_state(session, campaign),
            "character_effects": effects,
        }
        return {
            "preview_token": self._token(campaign_id, "exploration-chase", token_payload),
            "chase": {
                "id": event.id if event is not None else None,
                "version": event.version if event is not None else None,
                "title": str(payload["title"]),
                "successes": progress.successes,
                "failures": progress.failures,
                "target_successes": progress.target_successes,
                "target_failures": progress.target_failures,
                "status": progress.status,
                "outcome": str(payload["outcome"]),
            },
            "character_effects": effects,
            "world_time": world_time,
            "warnings": self._world_time_warnings(world_time),
        }

    def preview_trap_resolution(
        self, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            return {
                **self._trap_preview(session, campaign_id, scene_id, payload),
                "requires_confirmation": True,
            }

    def confirm_trap_resolution(
        self, campaign_id: str, scene_id: str, trap_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        clean = {
            key: value
            for key, value in payload.items()
            if key not in {"preview_token", "idempotency_key"}
        }
        with Session(self.engine) as session, session.begin():
            existing = self._operation(session, campaign_id, payload["idempotency_key"])
            if existing is not None:
                return self._operation_replay(existing)
            preview = self._trap_preview(session, campaign_id, scene_id, clean, trap_id=trap_id)
            if preview["preview_token"] != payload["preview_token"]:
                raise VersionConflict("trap preview", trap_id, 1, 2)
            campaign = self._campaign(session, campaign_id)
            scene = self._scene(session, campaign_id, scene_id)
            trap = self._trap(session, scene_id, trap_id)
            now = datetime.now(UTC)
            before = {"trap": serialize(trap), "world_clock": self._clock_state(session, campaign)}
            metadata = dict(trap.metadata_json or {})
            metadata["last_resolution"] = {
                "outcome": clean["outcome"],
                "summary": clean["summary"],
                "at": now.isoformat(),
            }
            trap.state = str(clean["result_state"])
            trap.metadata_json = metadata
            trap.version += 1
            trap.updated_at = now
            clock = self._advance_world_time(session, campaign, int(clean["minutes"]), now)
            character_effects = self._apply_character_effects(
                session,
                campaign_id,
                list(clean.get("character_effects") or []),
                source=f"陷阱：{trap.label}",
                now=now,
                effect_kind="trap",
            )
            event = Event(
                campaign_id=campaign_id,
                event_type="trap_resolution",
                title=trap.label,
                description=str(clean["summary"]),
                occurred_at=self._event_time(session, campaign, now),
                location_id=scene.location_id,
                visibility=str(clean["visibility"]),
                metadata_json={
                    "trap_id": trap.id,
                    "outcome": clean["outcome"],
                    "state": trap.state,
                },
            )
            session.add(event)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="trap_resolution",
                idempotency_key=payload["idempotency_key"],
                status="applied",
                before_snapshot=before,
                after_snapshot={},
                reason=str(clean["summary"]),
                source="dm",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            session.add(
                ExplorationTurn(
                    campaign_id=campaign_id,
                    scene_id=scene_id,
                    transaction_id=transaction.id,
                    minutes=int(clean["minutes"]),
                    action="trap",
                    result_json={
                        "trap_id": trap.id,
                        "outcome": clean["outcome"],
                        "state": trap.state,
                    },
                )
            )
            after = {
                "trap": serialize(trap),
                "event": serialize(event),
                "character_effects": character_effects,
                "world_clock": clock,
                "world_time": clock["current_time"],
                "operation_transaction_id": transaction.id,
            }
            transaction.after_snapshot = after
            session.flush()
            return {**after, "idempotent_replay": False}

    def _trap_preview(
        self,
        session: Session,
        campaign_id: str,
        scene_id: str,
        payload: dict[str, Any],
        *,
        trap_id: str | None = None,
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        self._scene(session, campaign_id, scene_id)
        resolved_trap_id = trap_id or str(payload.get("trap_id") or "")
        if not resolved_trap_id:
            raise ValueError("trap_id is required")
        trap = self._trap(session, scene_id, resolved_trap_id)
        expected = int(payload["trap_version"])
        if trap.version != expected:
            raise VersionConflict("scene object", trap.id, expected, trap.version)
        effects = self._preview_character_effects(
            session, campaign_id, list(payload.get("character_effects") or [])
        )
        world_time = self._world_time_preview(session, campaign, int(payload["minutes"]))
        token_payload = {
            # The trap id is a route parameter rather than a schema field.
            # Keep it explicit so preview and confirm hash the same payload.
            "request": {key: value for key, value in payload.items() if key != "trap_id"},
            "trap_id": trap.id,
            "trap": serialize(trap),
            "world_clock": self._clock_state(session, campaign),
            "character_effects": effects,
        }
        return {
            "preview_token": self._token(campaign_id, f"trap:{scene_id}:{trap.id}", token_payload),
            "trap": {
                "id": trap.id,
                "label": trap.label,
                "version": trap.version,
                "state_before": trap.state,
                "state_after": str(payload["result_state"]),
                "outcome": str(payload["outcome"]),
            },
            "character_effects": effects,
            "world_time": world_time,
            "warnings": self._world_time_warnings(world_time),
        }

    def preview_affliction(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            return {
                **self._affliction_preview(session, campaign_id, payload),
                "requires_confirmation": True,
            }

    def confirm_affliction(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        clean = {
            key: value
            for key, value in payload.items()
            if key not in {"preview_token", "idempotency_key"}
        }
        with Session(self.engine) as session, session.begin():
            existing = self._operation(session, campaign_id, payload["idempotency_key"])
            if existing is not None:
                return self._operation_replay(existing)
            preview = self._affliction_preview(session, campaign_id, clean)
            if preview["preview_token"] != payload["preview_token"]:
                raise VersionConflict("affliction preview", str(clean["character_id"]), 1, 2)
            campaign = self._campaign(session, campaign_id)
            character = self._character(session, campaign_id, str(clean["character_id"]))
            now = datetime.now(UTC)
            condition = self._condition(
                session,
                character.id,
                clean.get("condition_id"),
            )
            before = {
                "character": serialize(character),
                "condition": serialize(condition) if condition is not None else None,
                "world_clock": self._clock_state(session, campaign),
            }
            resolution = resolve_character_effect(
                hp=character.hp,
                max_hp=character.max_hp,
                max_hp_reduction=character.max_hp_reduction,
                damage=int(clean["damage"]),
                max_hp_reduction_delta=int(clean["max_hp_reduction"]),
            )
            character.hp = resolution.hp_after
            character.max_hp_reduction = resolution.max_hp_reduction_after
            character.version += 1
            character.updated_at = now
            operation = str(clean["operation"])
            if operation == "apply":
                condition = CharacterCondition(
                    character_id=character.id,
                    condition_name=str(clean["condition_name"]),
                    source=(str(clean["source"]) if clean.get("source") else None),
                    duration=(str(clean["duration"]) if clean.get("duration") else None),
                    notes=str(clean["summary"]),
                    details={
                        "affliction_type": clean["affliction_type"],
                        "status": "active",
                        "stage": 1,
                        "last_summary": clean["summary"],
                    },
                )
                session.add(condition)
            else:
                assert condition is not None
                details = dict(condition.details or {})
                if str(details.get("status") or "active") != "active":
                    raise ValueError("该毒药、疾病或感染已结束")
                if condition.condition_name != str(clean["condition_name"]):
                    raise ValueError("感染名称与目标状态不一致")
                current_affliction_type = details.get("affliction_type")
                if current_affliction_type and current_affliction_type != clean["affliction_type"]:
                    raise ValueError("毒药、疾病或感染类型与目标状态不一致")
                if operation == "progress":
                    details["stage"] = int(details.get("stage") or 1) + 1
                    details["last_summary"] = clean["summary"]
                else:
                    details["status"] = "cured"
                    details["cured_at"] = now.isoformat()
                    details["last_summary"] = clean["summary"]
                condition.details = details
                condition.notes = str(clean["summary"])
                condition.version += 1
                condition.updated_at = now
            session.flush()
            clock = self._advance_world_time(session, campaign, int(clean["minutes"]), now)
            event = Event(
                campaign_id=campaign_id,
                event_type="affliction",
                title=f"{clean['affliction_type']}：{clean['condition_name']}",
                description=str(clean["summary"]),
                occurred_at=self._event_time(session, campaign, now),
                location_id=campaign.current_location_id,
                visibility=str(clean["visibility"]),
                metadata_json={
                    "operation": operation,
                    "character_id": character.id,
                    "condition_id": condition.id if condition is not None else None,
                    "damage": int(clean["damage"]),
                    "max_hp_reduction": int(clean["max_hp_reduction"]),
                },
            )
            session.add(event)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="affliction",
                idempotency_key=payload["idempotency_key"],
                status="applied",
                before_snapshot=before,
                after_snapshot={},
                reason=str(clean["summary"]),
                source="dm",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            after = {
                "character": serialize(character),
                "condition": serialize(condition) if condition is not None else None,
                "event": serialize(event),
                "world_clock": clock,
                "world_time": clock["current_time"],
                "operation_transaction_id": transaction.id,
            }
            transaction.after_snapshot = after
            session.flush()
            return {**after, "idempotent_replay": False}

    def _affliction_preview(
        self, session: Session, campaign_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        character = self._character(session, campaign_id, str(payload["character_id"]))
        expected_character_version = int(payload["character_version"])
        if character.version != expected_character_version:
            raise VersionConflict(
                "character", character.id, expected_character_version, character.version
            )
        condition = self._condition(session, character.id, payload.get("condition_id"))
        if condition is not None:
            expected_condition_version = int(payload["condition_version"])
            if condition.version != expected_condition_version:
                raise VersionConflict(
                    "character condition",
                    condition.id,
                    expected_condition_version,
                    condition.version,
                )
            if condition.condition_name != str(payload["condition_name"]):
                raise ValueError("感染名称与目标状态不一致")
            details = dict(condition.details or {})
            if payload["operation"] != "apply":
                if str(details.get("status") or "active") != "active":
                    raise ValueError("该毒药、疾病或感染已结束")
                current_affliction_type = details.get("affliction_type")
                if (
                    current_affliction_type
                    and current_affliction_type != payload["affliction_type"]
                ):
                    raise ValueError("毒药、疾病或感染类型与目标状态不一致")
        resolution = resolve_character_effect(
            hp=character.hp,
            max_hp=character.max_hp,
            max_hp_reduction=character.max_hp_reduction,
            damage=int(payload["damage"]),
            max_hp_reduction_delta=int(payload["max_hp_reduction"]),
        )
        world_time = self._world_time_preview(session, campaign, int(payload["minutes"]))
        token_payload = {
            "request": payload,
            "character": serialize(character),
            "condition": serialize(condition) if condition is not None else None,
            "world_clock": self._clock_state(session, campaign),
        }
        return {
            "preview_token": self._token(campaign_id, f"affliction:{character.id}", token_payload),
            "character": {
                "id": character.id,
                "version": character.version,
                "hp_before": resolution.hp_before,
                "hp_after": resolution.hp_after,
                "max_hp_reduction_before": resolution.max_hp_reduction_before,
                "max_hp_reduction_after": resolution.max_hp_reduction_after,
            },
            "condition": {
                "id": condition.id if condition is not None else None,
                "version": condition.version if condition is not None else None,
                "operation": payload["operation"],
                "affliction_type": payload["affliction_type"],
                "status_after": "cured" if payload["operation"] == "cure" else "active",
                "stage_after": (
                    int(dict(condition.details or {}).get("stage") or 1) + 1
                    if condition is not None and payload["operation"] == "progress"
                    else 1
                ),
            },
            "world_time": world_time,
            "warnings": self._world_time_warnings(world_time),
        }

    def preview_downtime_resolution(
        self, campaign_id: str, activity_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            return {
                **self._downtime_preview(session, campaign_id, activity_id, payload),
                "requires_confirmation": True,
            }

    def confirm_downtime_resolution(
        self, campaign_id: str, activity_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        clean = {
            key: value
            for key, value in payload.items()
            if key not in {"preview_token", "idempotency_key"}
        }
        with Session(self.engine) as session, session.begin():
            existing = self._operation(session, campaign_id, payload["idempotency_key"])
            if existing is not None:
                return self._operation_replay(existing)
            preview = self._downtime_preview(session, campaign_id, activity_id, clean)
            if preview["preview_token"] != payload["preview_token"]:
                raise VersionConflict("downtime preview", activity_id, 1, 2)
            campaign = self._campaign(session, campaign_id)
            activity = self._downtime(session, campaign_id, activity_id)
            character = self._character(session, campaign_id, activity.character_id)
            wallet = self._character_wallet(session, campaign_id, character.id)
            now = datetime.now(UTC)
            progress = resolve_downtime_progress(
                progress_days=activity.progress_days,
                duration_days=activity.duration_days,
                requested_days=int(clean["progress_days"]),
                daily_cost_cp=activity.daily_cost_cp,
            )
            if progress.charged_days < 1:
                raise ValueError("该 Downtime 已完成")
            if progress.cost_copper and wallet is None:
                raise ValueError("该 Downtime 有每日成本，但角色没有钱包")
            if wallet is not None and wallet.copper < progress.cost_copper:
                raise ValueError("角色钱包余额不足，不能确认本次 Downtime")
            before = {
                "activity": serialize(activity),
                "character": serialize(character),
                "wallet": serialize(wallet) if wallet is not None else None,
                "world_clock": self._clock_state(session, campaign),
            }
            activity.progress_days = progress.progress_after
            activity.status = progress.status
            activity.details = {
                **dict(activity.details or {}),
                "last_summary": clean["summary"],
                "last_progress_days": progress.charged_days,
            }
            activity.version += 1
            activity.updated_at = now
            character.experience += int(clean["xp_award"])
            character.version += 1
            character.updated_at = now
            currency_transaction = None
            if wallet is not None and progress.cost_copper:
                wallet.copper -= progress.cost_copper
                wallet.version += 1
                wallet.updated_at = now
                currency_transaction = CurrencyTransaction(
                    campaign_id=campaign_id,
                    wallet_id=wallet.id,
                    amount_copper=-progress.cost_copper,
                    kind="adjustment",
                    idempotency_key=f"{payload['idempotency_key']}:downtime-cost",
                    metadata_json={"activity_id": activity.id, "reason": clean["summary"]},
                )
                session.add(currency_transaction)
            clock = self._advance_world_time(
                session, campaign, progress.charged_days * 24 * 60, now
            )
            event = Event(
                campaign_id=campaign_id,
                event_type="downtime",
                title=activity.title,
                description=str(clean["summary"]),
                occurred_at=self._event_time(session, campaign, now),
                location_id=campaign.current_location_id,
                visibility=str(clean["visibility"]),
                metadata_json={
                    "activity_id": activity.id,
                    "progress_days": progress.charged_days,
                    "xp_award": int(clean["xp_award"]),
                    "cost_copper": progress.cost_copper,
                    "status": progress.status,
                },
            )
            session.add(event)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="downtime_resolution",
                idempotency_key=payload["idempotency_key"],
                status="applied",
                before_snapshot=before,
                after_snapshot={},
                reason=str(clean["summary"]),
                source="dm",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            after = {
                "activity": serialize(activity),
                "character": serialize(character),
                "wallet": serialize(wallet) if wallet is not None else None,
                "currency_transaction": (
                    serialize(currency_transaction)
                    if currency_transaction is not None
                    else None
                ),
                "event": serialize(event),
                "world_clock": clock,
                "world_time": clock["current_time"],
                "operation_transaction_id": transaction.id,
            }
            transaction.after_snapshot = after
            session.flush()
            return {**after, "idempotent_replay": False}

    def _downtime_preview(
        self, session: Session, campaign_id: str, activity_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        activity = self._downtime(session, campaign_id, activity_id)
        if activity.version != int(payload["activity_version"]):
            raise VersionConflict(
                "downtime activity",
                activity.id,
                int(payload["activity_version"]),
                activity.version,
            )
        character = self._character(session, campaign_id, activity.character_id)
        if character.version != int(payload["character_version"]):
            raise VersionConflict(
                "character", character.id, int(payload["character_version"]), character.version
            )
        progress = resolve_downtime_progress(
            progress_days=activity.progress_days,
            duration_days=activity.duration_days,
            requested_days=int(payload["progress_days"]),
            daily_cost_cp=activity.daily_cost_cp,
        )
        if progress.charged_days < 1:
            raise ValueError("该 Downtime 已完成")
        wallet = self._character_wallet(session, campaign_id, character.id)
        if progress.cost_copper and wallet is None:
            raise ValueError("该 Downtime 有每日成本，但角色没有钱包")
        if wallet is not None and wallet.copper < progress.cost_copper:
            raise ValueError("角色钱包余额不足，不能确认本次 Downtime")
        world_time = self._world_time_preview(session, campaign, progress.charged_days * 24 * 60)
        token_payload = {
            "request": payload,
            "activity": serialize(activity),
            "character": serialize(character),
            "wallet": serialize(wallet) if wallet is not None else None,
            "world_clock": self._clock_state(session, campaign),
        }
        return {
            "preview_token": self._token(campaign_id, f"downtime:{activity.id}", token_payload),
            "activity": {
                "id": activity.id,
                "title": activity.title,
                "version": activity.version,
                "progress_before": progress.progress_before,
                "progress_after": progress.progress_after,
                "duration_days": progress.duration_days,
                "status_after": progress.status,
                "charged_days": progress.charged_days,
            },
            "wallet": {
                "id": wallet.id if wallet is not None else None,
                "before": wallet.copper if wallet is not None else 0,
                "after": (wallet.copper - progress.cost_copper) if wallet is not None else 0,
                "cost_copper": progress.cost_copper,
            },
            "experience": {
                "before": character.experience,
                "after": character.experience + int(payload["xp_award"]),
                "award": int(payload["xp_award"]),
            },
            "world_time": world_time,
            "warnings": self._world_time_warnings(world_time),
        }

    def preview_npc_morale(
        self, campaign_id: str, npc_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            return {
                **self._morale_preview(session, campaign_id, npc_id, payload),
                "requires_confirmation": True,
            }

    def confirm_npc_morale(
        self, campaign_id: str, npc_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        clean = {
            key: value
            for key, value in payload.items()
            if key not in {"preview_token", "idempotency_key"}
        }
        with Session(self.engine) as session, session.begin():
            existing = self._operation(session, campaign_id, payload["idempotency_key"])
            if existing is not None:
                return self._operation_replay(existing)
            preview = self._morale_preview(session, campaign_id, npc_id, clean)
            if preview["preview_token"] != payload["preview_token"]:
                raise VersionConflict("morale preview", npc_id, 1, 2)
            campaign = self._campaign(session, campaign_id)
            npc = self._npc(session, campaign_id, npc_id)
            combat, combatant = self._morale_combatant(
                session, campaign_id, npc.id, clean.get("combat_id")
            )
            now = datetime.now(UTC)
            before = {
                "npc": serialize(npc),
                "combat": serialize(combat) if combat is not None else None,
                "combatant": serialize(combatant) if combatant is not None else None,
                "world_clock": self._clock_state(session, campaign),
            }
            outcome = str(clean["outcome"])
            npc.status = {
                "hold": "active",
                "retreat": "retreated",
                "surrender": "surrendered",
            }[outcome]
            npc.version += 1
            npc.updated_at = now
            combat_result: dict[str, Any] | None = None
            if combatant is not None:
                snapshot = dict(combatant.snapshot_json or {})
                snapshot["morale_state"] = outcome
                snapshot["ai_mode"] = "dm_confirmation"
                combatant.snapshot_json = snapshot
                if bool(clean["leave_combat"]) and outcome in {"retreat", "surrender"}:
                    assert combat is not None
                    combat_result = self._remove_morale_combatant(session, combat, combatant, now)
                else:
                    combatant.version += 1
                    combatant.updated_at = now
                    combat_result = {"left_combat": False, "combatant_id": combatant.id}
            memory = NPCMemory(
                campaign_id=campaign_id,
                npc_id=npc.id,
                summary=str(clean["summary"]),
                memory_kind="morale",
                attitude_delta=0,
                tags=["morale", outcome],
                secret=str(clean["visibility"]) == "dm",
            )
            session.add(memory)
            clock = self._advance_world_time(session, campaign, int(clean["minutes"]), now)
            event = Event(
                campaign_id=campaign_id,
                event_type="npc_morale",
                title=f"{npc.name}：{outcome}",
                description=str(clean["summary"]),
                occurred_at=self._event_time(session, campaign, now),
                location_id=campaign.current_location_id,
                visibility=str(clean["visibility"]),
                metadata_json={
                    "npc_id": npc.id,
                    "outcome": outcome,
                    "combat_id": combat.id if combat is not None else None,
                    "combatant_id": combatant.id if combatant is not None else None,
                    "leave_combat": bool(clean["leave_combat"]),
                },
            )
            session.add(event)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="npc_morale",
                idempotency_key=payload["idempotency_key"],
                status="applied",
                before_snapshot=before,
                after_snapshot={},
                reason=str(clean["summary"]),
                source="dm",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            after = {
                "npc": serialize(npc),
                "npc_memory": serialize(memory),
                "combat": serialize(combat) if combat is not None else None,
                "combatant": serialize(combatant) if combatant is not None else None,
                "combat_result": combat_result,
                "event": serialize(event),
                "world_clock": clock,
                "world_time": clock["current_time"],
                "operation_transaction_id": transaction.id,
            }
            transaction.after_snapshot = after
            session.flush()
            return {**after, "idempotent_replay": False}

    def _morale_preview(
        self, session: Session, campaign_id: str, npc_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        npc = self._npc(session, campaign_id, npc_id)
        expected_npc_version = int(payload["npc_version"])
        if npc.version != expected_npc_version:
            raise VersionConflict("npc", npc.id, expected_npc_version, npc.version)
        combat, combatant = self._morale_combatant(
            session, campaign_id, npc.id, payload.get("combat_id")
        )
        if combat is not None:
            expected_combat_version = int(payload["combat_version"])
            if combat.version != expected_combat_version:
                raise VersionConflict("combat", combat.id, expected_combat_version, combat.version)
        world_time = self._world_time_preview(session, campaign, int(payload["minutes"]))
        token_payload = {
            "request": payload,
            "npc": serialize(npc),
            "combat": serialize(combat) if combat is not None else None,
            "combatant": serialize(combatant) if combatant is not None else None,
            "world_clock": self._clock_state(session, campaign),
        }
        return {
            "preview_token": self._token(campaign_id, f"morale:{npc.id}", token_payload),
            "npc": {
                "id": npc.id,
                "name": npc.name,
                "version": npc.version,
                "status_before": npc.status,
                "status_after": {
                    "hold": "active",
                    "retreat": "retreated",
                    "surrender": "surrendered",
                }[str(payload["outcome"])],
            },
            "combat": {
                "id": combat.id if combat is not None else None,
                "version": combat.version if combat is not None else None,
                "combatant_id": combatant.id if combatant is not None else None,
                "will_leave": bool(
                    combatant is not None
                    and payload["leave_combat"]
                    and payload["outcome"] in {"retreat", "surrender"}
                ),
            },
            "world_time": world_time,
            "warnings": self._world_time_warnings(world_time),
        }

    def preview_environment_hazard(
        self, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            return {
                **self._hazard_preview(session, campaign_id, scene_id, payload),
                "requires_confirmation": True,
            }

    def confirm_environment_hazard(
        self, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        clean = {
            key: value
            for key, value in payload.items()
            if key not in {"preview_token", "idempotency_key"}
        }
        with Session(self.engine) as session, session.begin():
            existing = self._operation(session, campaign_id, payload["idempotency_key"])
            if existing is not None:
                return self._operation_replay(existing)
            preview = self._hazard_preview(session, campaign_id, scene_id, clean)
            if preview["preview_token"] != payload["preview_token"]:
                raise VersionConflict("hazard preview", scene_id, 1, 2)
            campaign = self._campaign(session, campaign_id)
            scene = self._scene(session, campaign_id, scene_id)
            obj = self._scene_object(session, scene_id, clean.get("object_id"))
            now = datetime.now(UTC)
            before = {
                "object": serialize(obj) if obj is not None else None,
                "world_clock": self._clock_state(session, campaign),
            }
            if obj is not None:
                metadata = dict(obj.metadata_json or {})
                metadata["last_hazard"] = {
                    "name": clean["name"],
                    "summary": clean["summary"],
                    "at": now.isoformat(),
                }
                obj.metadata_json = metadata
                if clean.get("object_state") is not None:
                    obj.state = str(clean["object_state"])
                obj.version += 1
                obj.updated_at = now
            clock = self._advance_world_time(session, campaign, int(clean["minutes"]), now)
            character_effects = self._apply_character_effects(
                session,
                campaign_id,
                list(clean.get("character_effects") or []),
                source=f"环境危害：{clean['name']}",
                now=now,
                effect_kind="environment_hazard",
            )
            event = Event(
                campaign_id=campaign_id,
                event_type="environment_hazard",
                title=str(clean["name"]),
                description=str(clean["summary"]),
                occurred_at=self._event_time(session, campaign, now),
                location_id=scene.location_id,
                visibility=str(clean["visibility"]),
                metadata_json={
                    "scene_id": scene.id,
                    "object_id": obj.id if obj is not None else None,
                },
            )
            session.add(event)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="environment_hazard",
                idempotency_key=payload["idempotency_key"],
                status="applied",
                before_snapshot=before,
                after_snapshot={},
                reason=str(clean["summary"]),
                source="dm",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            session.add(
                ExplorationTurn(
                    campaign_id=campaign_id,
                    scene_id=scene_id,
                    transaction_id=transaction.id,
                    minutes=int(clean["minutes"]),
                    action="environment_hazard",
                    result_json={
                        "name": clean["name"],
                        "object_id": obj.id if obj is not None else None,
                    },
                )
            )
            after = {
                "object": serialize(obj) if obj is not None else None,
                "event": serialize(event),
                "character_effects": character_effects,
                "world_clock": clock,
                "world_time": clock["current_time"],
                "operation_transaction_id": transaction.id,
            }
            transaction.after_snapshot = after
            session.flush()
            return {**after, "idempotent_replay": False}

    def _hazard_preview(
        self, session: Session, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        self._scene(session, campaign_id, scene_id)
        obj = self._scene_object(session, scene_id, payload.get("object_id"))
        if obj is not None:
            expected_object_version = int(payload["object_version"])
            if obj.version != expected_object_version:
                raise VersionConflict("scene object", obj.id, expected_object_version, obj.version)
        effects = self._preview_character_effects(
            session, campaign_id, list(payload.get("character_effects") or [])
        )
        world_time = self._world_time_preview(session, campaign, int(payload["minutes"]))
        token_payload = {
            "request": payload,
            "object": serialize(obj) if obj is not None else None,
            "character_effects": effects,
            "world_clock": self._clock_state(session, campaign),
        }
        return {
            "preview_token": self._token(campaign_id, f"hazard:{scene_id}", token_payload),
            "hazard": {
                "name": payload["name"],
                "object_id": obj.id if obj is not None else None,
                "object_state_before": obj.state if obj is not None else None,
                "object_state_after": payload.get("object_state") if obj is not None else None,
            },
            "character_effects": effects,
            "world_time": world_time,
            "warnings": self._world_time_warnings(world_time),
        }

    def _social_preview(
        self, session: Session, campaign_id: str, npc_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        npc = self._npc(session, campaign_id, npc_id)
        expected_version = int(payload["npc_version"])
        if npc.version != expected_version:
            raise VersionConflict("npc", npc.id, expected_version, npc.version)

        transition = resolve_social_attitude(npc.attitude, str(payload["outcome"]))
        clock = session.scalar(select(WorldClock).where(WorldClock.campaign_id == campaign_id))
        current_time = clock.current_time if clock is not None else campaign.current_time
        paused = bool(clock.paused) if clock is not None else False
        resulting_time = current_time
        if current_time and not paused:
            resulting_time = current_time + timedelta(minutes=int(payload["minutes"]))

        warnings: list[str] = []
        if transition.normalized_from_nonstandard:
            warnings.append("NPC 的现有态度不是标准档位；本次按 indifferent 处理并会写回标准态度。")
        if current_time is None:
            warnings.append("战役尚未设置世界时间；确认仍会记录社交记忆，但不会推进时间。")
        elif paused:
            warnings.append("世界时钟已暂停；确认不会推进时间。")

        token_payload = {
            "request": payload,
            "npc": {
                "id": npc.id,
                "version": npc.version,
                "attitude": npc.attitude,
            },
            "world_clock": self._clock_state(session, campaign),
        }
        return {
            "preview_token": self._token(campaign_id, f"social:{npc_id}", token_payload),
            "npc": {
                "id": npc.id,
                "name": npc.name,
                "version": npc.version,
                "attitude": {
                    "before": transition.before,
                    "after": transition.after,
                    "requested_delta": transition.requested_delta,
                    "effective_delta": transition.effective_delta,
                },
            },
            "memory": {
                "summary": payload["summary"],
                "memory_kind": payload["memory_kind"],
                "attitude_delta": transition.effective_delta,
                "tags": list(payload.get("tags") or []),
                "secret": bool(payload.get("secret", False)),
            },
            "world_time": {
                "before": current_time.isoformat() if current_time else None,
                "after": resulting_time.isoformat() if resulting_time else None,
                "minutes": int(payload["minutes"]),
                "paused": paused,
            },
            "warnings": warnings,
        }

    def _exploration_preview(
        self, session: Session, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the same deterministic preview used by confirm.

        Keep this as a single helper so a changed grid/object state cannot be
        silently confirmed from a stale preview. The token includes the
        caller payload and the confirm path compares it against the current
        world before mutating anything.
        """
        grid = self._grid(session, campaign_id, scene_id)
        result = self._explore_result(session, grid, scene_id, payload)
        return {
            "preview_token": self._token(campaign_id, scene_id, payload),
            "scene_id": scene_id,
            "result": result,
        }

    def _travel_preview(
        self, session: Session, campaign_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._campaign(session, campaign_id)
        self._location_exists(session, campaign_id, payload["to_location_id"])
        duration = travel_minutes(float(payload["distance_miles"]), payload["pace"])
        world_time = self._world_time_preview(session, campaign, duration)
        token_payload = {
            "request": payload,
            "campaign": {
                "id": campaign.id,
                "version": campaign.version,
                "current_location_id": campaign.current_location_id,
            },
            "world_clock": self._clock_state(session, campaign),
        }
        return {
            "preview_token": self._token(campaign_id, "travel", token_payload),
            "duration_minutes": duration,
            "from_location_id": campaign.current_location_id,
            "to_location_id": payload["to_location_id"],
            "encounter": payload.get("encounter"),
            "world_time": world_time,
            "warnings": self._world_time_warnings(world_time),
        }

    @staticmethod
    def _operation(
        session: Session, campaign_id: str, idempotency_key: str
    ) -> OperationTransaction | None:
        return session.scalar(
            select(OperationTransaction).where(
                OperationTransaction.campaign_id == campaign_id,
                OperationTransaction.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def _operation_replay(existing: OperationTransaction) -> dict[str, Any]:
        return {
            **dict(existing.after_snapshot or {}),
            "idempotent_replay": True,
            "operation_transaction_id": existing.id,
        }

    @staticmethod
    def _chase_event(
        session: Session, campaign_id: str, event_id: object | None
    ) -> Event | None:
        if event_id is None:
            return None
        row = session.get(Event, str(event_id))
        if (
            row is None
            or row.campaign_id != campaign_id
            or row.event_type != "exploration_chase"
        ):
            raise StateNotFoundError("chase event not found in campaign")
        return row

    @staticmethod
    def _trap(session: Session, scene_id: str, trap_id: str) -> SceneObject:
        row = session.get(SceneObject, trap_id)
        if row is None or row.scene_id != scene_id or row.object_type != "trap":
            raise StateNotFoundError("trap not found in scene")
        return row

    @staticmethod
    def _scene_object(
        session: Session, scene_id: str, object_id: object | None
    ) -> SceneObject | None:
        if object_id is None:
            return None
        row = session.get(SceneObject, str(object_id))
        if row is None or row.scene_id != scene_id:
            raise StateNotFoundError("scene object not found in scene")
        return row

    @staticmethod
    def _character(session: Session, campaign_id: str, character_id: str) -> Character:
        row = session.get(Character, character_id)
        if row is None or row.campaign_id != campaign_id:
            raise StateNotFoundError("character not found in campaign")
        return row

    @staticmethod
    def _condition(
        session: Session, character_id: str, condition_id: object | None
    ) -> CharacterCondition | None:
        if condition_id is None:
            return None
        row = session.get(CharacterCondition, str(condition_id))
        if row is None or row.character_id != character_id:
            raise StateNotFoundError("character condition not found")
        return row

    @staticmethod
    def _downtime(session: Session, campaign_id: str, activity_id: str) -> DowntimeActivity:
        row = session.get(DowntimeActivity, activity_id)
        if row is None or row.campaign_id != campaign_id:
            raise StateNotFoundError("downtime activity not found in campaign")
        return row

    @staticmethod
    def _character_wallet(session: Session, campaign_id: str, character_id: str) -> Wallet | None:
        return session.scalar(
            select(Wallet).where(
                Wallet.campaign_id == campaign_id,
                Wallet.character_id == character_id,
            )
        )

    def _preview_character_effects(
        self, session: Session, campaign_id: str, effects: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for effect in effects:
            character = self._character(session, campaign_id, str(effect["character_id"]))
            expected_version = int(effect["character_version"])
            if character.version != expected_version:
                raise VersionConflict(
                    "character", character.id, expected_version, character.version
                )
            resolution = resolve_character_effect(
                hp=character.hp,
                max_hp=character.max_hp,
                max_hp_reduction=character.max_hp_reduction,
                damage=int(effect.get("damage") or 0),
                max_hp_reduction_delta=int(effect.get("max_hp_reduction") or 0),
            )
            result.append(
                {
                    "character_id": character.id,
                    "character_name": character.name,
                    "version": character.version,
                    "hp_before": resolution.hp_before,
                    "hp_after": resolution.hp_after,
                    "max_hp_reduction_before": resolution.max_hp_reduction_before,
                    "max_hp_reduction_after": resolution.max_hp_reduction_after,
                    "effective_max_hp_after": resolution.effective_max_hp_after,
                    "condition_name": effect.get("condition_name"),
                    "condition_duration": effect.get("condition_duration"),
                }
            )
        return result

    def _apply_character_effects(
        self,
        session: Session,
        campaign_id: str,
        effects: list[dict[str, Any]],
        *,
        source: str,
        now: datetime,
        effect_kind: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for effect in effects:
            character = self._character(session, campaign_id, str(effect["character_id"]))
            expected_version = int(effect["character_version"])
            if character.version != expected_version:
                raise VersionConflict(
                    "character", character.id, expected_version, character.version
                )
            resolution = resolve_character_effect(
                hp=character.hp,
                max_hp=character.max_hp,
                max_hp_reduction=character.max_hp_reduction,
                damage=int(effect.get("damage") or 0),
                max_hp_reduction_delta=int(effect.get("max_hp_reduction") or 0),
            )
            before = serialize(character)
            character.hp = resolution.hp_after
            character.max_hp_reduction = resolution.max_hp_reduction_after
            character.version += 1
            character.updated_at = now
            condition = None
            if effect.get("condition_name"):
                condition = CharacterCondition(
                    character_id=character.id,
                    condition_name=str(effect["condition_name"]),
                    source=source,
                    duration=(
                        str(effect["condition_duration"])
                        if effect.get("condition_duration")
                        else None
                    ),
                    notes=(
                        str(effect["condition_notes"])
                        if effect.get("condition_notes")
                        else None
                    ),
                    details={"status": "active", "effect_kind": effect_kind},
                )
                session.add(condition)
            session.flush()
            result.append(
                {
                    "before": before,
                    "character": serialize(character),
                    "condition": serialize(condition) if condition is not None else None,
                }
            )
        return result

    @staticmethod
    def _morale_combatant(
        session: Session, campaign_id: str, npc_id: str, combat_id: object | None
    ) -> tuple[Combat | None, Combatant | None]:
        if combat_id is None:
            return None, None
        combat = session.get(Combat, str(combat_id))
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        rows = session.scalars(
            select(Combatant).where(
                Combatant.combat_id == combat.id,
                Combatant.entity_type == "npc",
                Combatant.entity_id == npc_id,
                Combatant.is_active.is_(True),
            )
        ).all()
        if len(rows) > 1:
            raise ValueError("该 NPC 在战斗中有多个单位，请由 DM 先分别处理")
        return combat, (rows[0] if rows else None)

    @staticmethod
    def _remove_morale_combatant(
        session: Session, combat: Combat, combatant: Combatant, now: datetime
    ) -> dict[str, Any]:
        ordered_before = list(
            session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
        )
        active_id = (
            ordered_before[combat.current_turn_index].id
            if ordered_before and combat.current_turn_index < len(ordered_before)
            else None
        )
        combatant.is_active = False
        combatant.version += 1
        combatant.updated_at = now
        session.flush()
        ordered_after = [item for item in ordered_before if item.id != combatant.id]
        if ordered_after:
            if active_id and active_id != combatant.id:
                combat.current_turn_index = next(
                    index for index, item in enumerate(ordered_after) if item.id == active_id
                )
            else:
                combat.current_turn_index = min(combat.current_turn_index, len(ordered_after) - 1)
        else:
            combat.current_turn_index = 0
        combat.version += 1
        combat.updated_at = now
        return {
            "left_combat": True,
            "combatant_id": combatant.id,
            "active_combatant_id": (
                ordered_after[combat.current_turn_index].id if ordered_after else None
            ),
        }

    def _world_time_preview(
        self, session: Session, campaign: Campaign, minutes: int
    ) -> dict[str, Any]:
        clock = session.scalar(select(WorldClock).where(WorldClock.campaign_id == campaign.id))
        current_time = clock.current_time if clock is not None else campaign.current_time
        paused = bool(clock.paused) if clock is not None else False
        resulting_time = (
            current_time + timedelta(minutes=minutes)
            if current_time is not None and not paused
            else current_time
        )
        return {
            "before": current_time.isoformat() if current_time else None,
            "after": resulting_time.isoformat() if resulting_time else None,
            "minutes": minutes,
            "paused": paused,
        }

    @staticmethod
    def _world_time_warnings(world_time: dict[str, Any]) -> list[str]:
        if world_time["before"] is None:
            return ["战役尚未设置世界时间；确认会写入状态，但不会推进时钟。"]
        if world_time["paused"]:
            return ["世界时钟已暂停；确认会写入状态，但不会推进时钟。"]
        return []

    def _clock_state(self, session: Session, campaign: Campaign) -> dict[str, Any]:
        # Previews call this helper as part of their concurrency token.  Do
        # not materialize a WorldClock merely to inspect it: a preview must be
        # read-only even when the campaign still relies on current_time.
        clock = session.scalar(select(WorldClock).where(WorldClock.campaign_id == campaign.id))
        if clock is None:
            return {
                "current_time": (
                    campaign.current_time.isoformat() if campaign.current_time else None
                ),
                "paused": False,
                "version": 0,
            }
        return {
            "current_time": clock.current_time.isoformat() if clock.current_time else None,
            "paused": bool(clock.paused),
            "version": clock.version,
        }

    def _advance_world_time(
        self,
        session: Session,
        campaign: Campaign,
        minutes: int,
        now: datetime,
        *,
        update_campaign: bool = True,
    ) -> dict[str, Any]:
        if minutes < 0:
            raise ValueError("minutes must not be negative")
        clock = self._clock(session, campaign)
        if minutes > 0 and clock.current_time is not None and not clock.paused:
            clock.current_time += timedelta(minutes=minutes)
            clock.version += 1
            clock.updated_at = now
            campaign.current_time = clock.current_time
            if update_campaign:
                campaign.version += 1
                campaign.updated_at = now
        return self._clock_state(session, campaign)

    def _event_time(self, session: Session, campaign: Campaign, fallback: datetime) -> datetime:
        clock = self._clock(session, campaign)
        return clock.current_time or campaign.current_time or fallback

    def _explore_result(
        self, s: Session, grid: SceneGrid, scene_id: str, p: dict[str, Any]
    ) -> dict[str, Any]:
        result = {"action": p["action"], "minutes": p["minutes"]}
        if p["action"] == "move":
            path = [(int(x[0]), int(x[1])) for x in p.get("path", [])]
            if len(path) < 2:
                raise ValueError("movement needs at least two cells")
            for r, c in path:
                self._bounds(grid, r, c, 1)
            difficult = {
                (o.row, o.col)
                for o in s.scalars(
                    select(SceneObject).where(
                        SceneObject.scene_id == scene_id,
                        SceneObject.object_type == "terrain",
                        SceneObject.state == "active",
                    )
                )
                if bool((o.metadata_json or {}).get("difficult", True))
            }
            result["movement_cost_ft"] = movement_cost_ft(
                path, difficult, cell_size_ft=grid.cell_size_ft
            )
            result["end"] = {"row": path[-1][0], "col": path[-1][1]}
        if p["action"] == "interact" and p.get("object_id"):
            obj = s.get(SceneObject, p["object_id"])
            result["object"] = serialize(obj) if obj else None
        return result

    def _scene(self, s: Session, cid: str, sid: str) -> Scene:
        row = s.get(Scene, sid)
        if row is None or row.campaign_id != cid:
            raise StateNotFoundError("scene not found")
        return row

    def _grid(self, s: Session, cid: str, sid: str) -> SceneGrid:
        self._scene(s, cid, sid)
        row = s.scalar(select(SceneGrid).where(SceneGrid.scene_id == sid))
        if row is None:
            raise StateNotFoundError("scene grid not found")
        return row

    def _campaign(self, s: Session, cid: str) -> Campaign:
        row = s.get(Campaign, cid)
        if row is None:
            raise StateNotFoundError("campaign not found")
        return row

    @staticmethod
    def _npc(s: Session, campaign_id: str, npc_id: str) -> NPC:
        row = s.get(NPC, npc_id)
        if row is None or row.campaign_id != campaign_id:
            raise StateNotFoundError("npc not found in campaign")
        return row

    def _clock(self, s: Session, c: Campaign) -> WorldClock:
        row = s.scalar(select(WorldClock).where(WorldClock.campaign_id == c.id))
        if row is None:
            row = WorldClock(campaign_id=c.id, current_time=c.current_time)
            s.add(row)
            s.flush()
        return row

    def _location_exists(self, s: Session, cid: str, lid: str) -> None:
        row = s.get(Location, lid)
        if row is None or row.campaign_id != cid:
            raise StateNotFoundError("location not found")

    @staticmethod
    def _bounds(g: SceneGrid, r: int, c: int, size: int) -> None:
        if r + size - 1 > g.height or c + size - 1 > g.width:
            raise ValueError("position is outside scene grid")

    @staticmethod
    def _token(cid: str, sid: str, p: dict[str, Any]) -> str:
        raw = json.dumps(
            {"campaign": cid, "scope": sid, "payload": p}, sort_keys=True, default=str
        ).encode()
        return hashlib.sha256(raw).hexdigest()
