from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.domain.exploration import movement_cost_ft, travel_minutes
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    ExplorationTurn,
    OperationTransaction,
    Scene,
    SceneGrid,
    SceneObject,
    SceneToken,
    TravelLeg,
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
        kind_map = {
            "wall": "wall",
            "door": "door",
            "cover": "cover",
            "object": "furniture",
        }
        seen: set[tuple[int, int]] = set()
        for cell in raw_cells[:500]:
            if not isinstance(cell, dict):
                continue
            object_type = kind_map.get(str(cell.get("kind", "")))
            if object_type is None:
                continue
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
                    metadata_json={"generated_from": "layers_json"},
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
            grid = self._grid(s, campaign_id, scene_id)
            result = self._explore_result(s, grid, scene_id, payload)
            return {
                "preview_token": self._token(campaign_id, scene_id, payload),
                "scene_id": scene_id,
                "result": result,
                "requires_confirmation": True,
            }

    def confirm_exploration(
        self, campaign_id: str, scene_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        clean = {k: v for k, v in payload.items() if k not in {"preview_token", "idempotency_key"}}
        if payload["preview_token"] != self._token(campaign_id, scene_id, clean):
            raise ValueError("exploration preview expired or changed")
        with Session(self.engine) as s, s.begin():
            existing = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == payload["idempotency_key"],
                )
            )
            if existing:
                return dict(existing.after_snapshot)
            grid = self._grid(s, campaign_id, scene_id)
            result = self._explore_result(s, grid, scene_id, clean)
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
            clock = self._clock(s, campaign)
            before["world_time"] = clock.current_time.isoformat() if clock.current_time else None
            if not clock.paused and clock.current_time:
                clock.current_time += timedelta(minutes=int(clean["minutes"]))
                campaign.current_time = clock.current_time
            after["world_time"] = clock.current_time.isoformat() if clock.current_time else None
            tx = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="exploration_turn",
                idempotency_key=payload["idempotency_key"],
                before_snapshot=before,
                after_snapshot=after,
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
            return after

    def preview_travel(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as s:
            campaign = self._campaign(s, campaign_id)
            self._location_exists(s, campaign_id, payload["to_location_id"])
            duration = travel_minutes(float(payload["distance_miles"]), payload["pace"])
            return {
                "preview_token": self._token(campaign_id, "travel", payload),
                "duration_minutes": duration,
                "from_location_id": campaign.current_location_id,
                "to_location_id": payload["to_location_id"],
                "requires_confirmation": True,
            }

    def confirm_travel(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        clean = {k: v for k, v in payload.items() if k not in {"preview_token", "idempotency_key"}}
        if payload["preview_token"] != self._token(campaign_id, "travel", clean):
            raise ValueError("travel preview expired or changed")
        with Session(self.engine) as s, s.begin():
            existing = s.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == payload["idempotency_key"],
                )
            )
            if existing:
                return dict(existing.after_snapshot)
            campaign = self._campaign(s, campaign_id)
            self._location_exists(s, campaign_id, clean["to_location_id"])
            duration = travel_minutes(float(clean["distance_miles"]), clean["pace"])
            clock = self._clock(s, campaign)
            before = {
                "location_id": campaign.current_location_id,
                "world_time": clock.current_time.isoformat() if clock.current_time else None,
            }
            campaign.current_location_id = clean["to_location_id"]
            if clock.current_time and not clock.paused:
                clock.current_time += timedelta(minutes=duration)
                campaign.current_time = clock.current_time
            after = {
                "location_id": campaign.current_location_id,
                "duration_minutes": duration,
                "world_time": clock.current_time.isoformat() if clock.current_time else None,
            }
            tx = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="travel_leg",
                idempotency_key=payload["idempotency_key"],
                before_snapshot=before,
                after_snapshot=after,
                reason=clean.get("notes"),
                source="dm",
                confirmed_at=datetime.now(UTC),
            )
            s.add(tx)
            s.flush()
            s.add(
                TravelLeg(
                    campaign_id=campaign_id,
                    from_location_id=before["location_id"],
                    to_location_id=clean["to_location_id"],
                    transaction_id=tx.id,
                    distance_miles=float(clean["distance_miles"]),
                    pace=clean["pace"],
                    duration_minutes=duration,
                    details_json={"notes": clean.get("notes")},
                )
            )
            return after

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

    def _clock(self, s: Session, c: Campaign) -> WorldClock:
        row = s.scalar(select(WorldClock).where(WorldClock.campaign_id == c.id))
        if row is None:
            row = WorldClock(campaign_id=c.id, current_time=c.current_time)
            s.add(row)
            s.flush()
        return row

    def _location_exists(self, s: Session, cid: str, lid: str) -> None:
        from dnd_dm_assistant.infrastructure.database.models import Location

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
