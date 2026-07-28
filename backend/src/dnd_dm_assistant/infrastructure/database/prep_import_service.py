from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.domain.prep_draft import (
    DuplicateStrategy,
    PrepDraft,
    PrepValidationIssue,
)
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Clue,
    Location,
    MonsterInstance,
    OperationTransaction,
    Quest,
    Scene,
    SceneGrid,
    SceneParticipant,
    WorldItem,
)

ENTITY_ORDER = ("locations", "scenes", "npcs", "monsters", "quests", "clues", "items")
MODEL_BY_TYPE = {
    "locations": Location,
    "scenes": Scene,
    "npcs": NPC,
    "monsters": MonsterInstance,
    "quests": Quest,
    "clues": Clue,
    "items": WorldItem,
}


class PrepImportService:
    """Validate and atomically materialize a versioned preparation draft.

    Preview and confirmation deliberately share the same semantic validator.
    Confirmation recomputes both duplicate decisions and reference scope in its
    write transaction, so a stale preview cannot silently import a different plan.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def validate(
        self,
        campaign_id: str,
        draft: PrepDraft,
        duplicate_strategy: DuplicateStrategy,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            campaign = self._campaign(session, campaign_id)
            return self._validation(session, campaign, draft, duplicate_strategy)

    def preview(
        self,
        campaign_id: str,
        draft: PrepDraft,
        duplicate_strategy: DuplicateStrategy,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            campaign = self._campaign(session, campaign_id)
            result = self._validation(session, campaign, draft, duplicate_strategy)
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        result["preview_token"] = self._token(
            campaign_id, draft, duplicate_strategy, result, expires_at
        )
        result["expires_at"] = expires_at
        return result

    def confirm(
        self,
        campaign_id: str,
        draft: PrepDraft,
        duplicate_strategy: DuplicateStrategy,
        *,
        preview_token: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        expires_at = self._expires_at(preview_token)
        if expires_at <= datetime.now(UTC):
            raise ValueError("prep import preview expired")
        transaction_key = f"prep-import:{idempotency_key}"
        draft_hash = self._draft_hash(draft, duplicate_strategy)
        with Session(self.engine) as session, session.begin():
            campaign = self._campaign(session, campaign_id)
            existing = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == transaction_key,
                )
            )
            if existing is not None:
                if (
                    existing.operation_type != "prep_import"
                    or existing.before_snapshot.get("draft_hash") != draft_hash
                ):
                    raise ValueError("idempotency key was already used by another operation")
                replay = dict(existing.after_snapshot)
                replay["idempotent_replay"] = True
                return replay

            validation = self._validation(session, campaign, draft, duplicate_strategy)
            expected_token = self._token(
                campaign_id, draft, duplicate_strategy, validation, expires_at
            )
            if not secrets.compare_digest(preview_token, expected_token):
                raise ValueError("prep import preview is stale or does not match this draft")
            if not validation["valid"]:
                messages = "; ".join(issue["message"] for issue in validation["errors"][:5])
                raise ValueError(f"prep draft is invalid: {messages}")

            reference_map = self._initial_reuse_map(validation)
            created = {entity_type: 0 for entity_type in ENTITY_ORDER}
            reused = {
                entity_type: len(reference_map[entity_type]) for entity_type in ENTITY_ORDER
            }
            created_ids: dict[str, list[str]] = {
                entity_type: [] for entity_type in ENTITY_ORDER
            }

            self._create_locations(
                session, campaign_id, draft, reference_map, created, created_ids
            )
            self._create_npcs(session, campaign_id, draft, reference_map, created, created_ids)
            self._create_monsters(
                session, campaign_id, draft, reference_map, created, created_ids
            )
            self._create_quests(session, campaign_id, draft, reference_map, created, created_ids)
            self._create_scenes(session, campaign_id, draft, reference_map, created, created_ids)
            self._create_clues(session, campaign_id, draft, reference_map, created, created_ids)
            self._create_items(session, campaign_id, draft, reference_map, created, created_ids)
            session.flush()

            result: dict[str, Any] = {
                "import_id": "",
                "idempotent_replay": False,
                "created": created,
                "reused": reused,
                "reference_map": reference_map,
            }
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="prep_import",
                idempotency_key=transaction_key,
                status="applied",
                before_snapshot={
                    "draft_hash": draft_hash,
                    "schema_version": draft.schema_version,
                },
                after_snapshot={},
                reason=draft.title or "Versioned preparation draft import",
                source="game_table",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            result["import_id"] = transaction.id
            transaction.after_snapshot = dict(result)
            return result

    def _validation(
        self,
        session: Session,
        campaign: Campaign,
        draft: PrepDraft,
        duplicate_strategy: DuplicateStrategy,
    ) -> dict[str, Any]:
        warnings: list[PrepValidationIssue] = []
        errors: list[PrepValidationIssue] = []
        self._validate_campaign(campaign, errors)
        self._validate_keys_and_names(draft, errors)
        self._validate_references(draft, errors)
        existing = self._existing_by_name(session, campaign.id)
        operations: list[dict[str, Any]] = []
        reference_plan: dict[str, dict[str, str]] = {
            entity_type: {} for entity_type in ENTITY_ORDER
        }
        summary: dict[str, int] = {}
        for entity_type in ENTITY_ORDER:
            rows = getattr(draft, entity_type)
            summary[entity_type] = len(rows)
            for index, row in enumerate(rows):
                match = existing[entity_type].get(self._normalize_name(row.name))
                action = "create"
                matched_id: str | None = None
                if match is not None:
                    if duplicate_strategy == "error":
                        errors.append(
                            PrepValidationIssue(
                                code="duplicate_existing",
                                path=f"{entity_type}.{index}.name",
                                message=(
                                    f"{entity_type[:-1]} named '{row.name}' already exists"
                                ),
                            )
                        )
                        action = "blocked"
                    elif duplicate_strategy == "reuse":
                        action = "reuse"
                        matched_id = str(match.id)
                        reference_plan[entity_type][row.key] = matched_id
                        warnings.append(
                            PrepValidationIssue(
                                code="duplicate_reused",
                                path=f"{entity_type}.{index}.name",
                                message=(
                                    f"Existing {entity_type[:-1]} '{row.name}' will be reused"
                                ),
                            )
                        )
                operations.append(
                    {
                        "entity_type": entity_type,
                        "key": row.key,
                        "name": row.name,
                        "action": action,
                        "matched_id": matched_id,
                    }
                )
                if action == "create":
                    reference_plan[entity_type][row.key] = "new"
        return {
            "valid": not errors,
            "summary": summary,
            "warnings": [item.model_dump(mode="json") for item in warnings],
            "errors": [item.model_dump(mode="json") for item in errors],
            "operations": operations,
            "reference_plan": reference_plan,
        }

    @staticmethod
    def _validate_campaign(campaign: Campaign, errors: list[PrepValidationIssue]) -> None:
        if campaign.ruleset != "dnd5e" or campaign.primary_rules_year != 2024:
            errors.append(
                PrepValidationIssue(
                    code="ruleset_mismatch",
                    path="schema_version",
                    message="Preparation imports require the D&D 5e 2024 campaign ruleset",
                )
            )

    def _validate_keys_and_names(
        self, draft: PrepDraft, errors: list[PrepValidationIssue]
    ) -> None:
        for entity_type in ENTITY_ORDER:
            keys: set[str] = set()
            for index, row in enumerate(getattr(draft, entity_type)):
                if row.key in keys:
                    errors.append(
                        PrepValidationIssue(
                            code="duplicate_key",
                            path=f"{entity_type}.{index}.key",
                            message=f"Duplicate {entity_type} key '{row.key}'",
                        )
                    )
                keys.add(row.key)

    @staticmethod
    def _validate_references(draft: PrepDraft, errors: list[PrepValidationIssue]) -> None:
        locations = {row.key for row in draft.locations}
        npcs = {row.key for row in draft.npcs}
        monsters = {row.key for row in draft.monsters}
        quests = {row.key for row in draft.quests}
        for index, location in enumerate(draft.locations):
            if (
                location.parent_location_key is not None
                and location.parent_location_key not in locations
            ):
                errors.append(
                    PrepValidationIssue(
                        code="missing_reference",
                        path=f"locations.{index}.parent_location_key",
                        message=f"Unknown location key '{location.parent_location_key}'",
                    )
                )
        PrepImportService._validate_location_cycles(draft, errors)
        for index, scene in enumerate(draft.scenes):
            if scene.location_key is not None and scene.location_key not in locations:
                errors.append(
                    PrepValidationIssue(
                        code="missing_reference",
                        path=f"scenes.{index}.location_key",
                        message=f"Unknown location key '{scene.location_key}'",
                    )
                )
            for participant_index, participant in enumerate(scene.participants):
                candidates = npcs if participant.entity_type == "npc" else monsters
                if participant.entity_key not in candidates:
                    errors.append(
                        PrepValidationIssue(
                            code="missing_reference",
                            path=f"scenes.{index}.participants.{participant_index}.entity_key",
                            message=(
                                f"Unknown {participant.entity_type} key "
                                f"'{participant.entity_key}'"
                            ),
                        )
                    )
        for index, npc in enumerate(draft.npcs):
            if npc.location_key is not None and npc.location_key not in locations:
                errors.append(
                    PrepValidationIssue(
                        code="missing_reference",
                        path=f"npcs.{index}.location_key",
                        message=f"Unknown location key '{npc.location_key}'",
                    )
                )
        for index, quest in enumerate(draft.quests):
            if quest.giver_npc_key is not None and quest.giver_npc_key not in npcs:
                errors.append(
                    PrepValidationIssue(
                        code="missing_reference",
                        path=f"quests.{index}.giver_npc_key",
                        message=f"Unknown NPC key '{quest.giver_npc_key}'",
                    )
                )
        for index, clue in enumerate(draft.clues):
            if clue.quest_key is not None and clue.quest_key not in quests:
                errors.append(
                    PrepValidationIssue(
                        code="missing_reference",
                        path=f"clues.{index}.quest_key",
                        message=f"Unknown quest key '{clue.quest_key}'",
                    )
                )
        for index, item in enumerate(draft.items):
            if item.location_key not in locations:
                errors.append(
                    PrepValidationIssue(
                        code="missing_reference",
                        path=f"items.{index}.location_key",
                        message=f"Unknown location key '{item.location_key}'",
                    )
                )

    @staticmethod
    def _validate_location_cycles(
        draft: PrepDraft, errors: list[PrepValidationIssue]
    ) -> None:
        parents = {row.key: row.parent_location_key for row in draft.locations}
        for key in parents:
            seen: set[str] = set()
            current: str | None = key
            while current is not None:
                if current in seen:
                    errors.append(
                        PrepValidationIssue(
                            code="location_cycle",
                            path=f"locations.{key}.parent_location_key",
                            message=f"Location parent cycle includes '{current}'",
                        )
                    )
                    break
                seen.add(current)
                current = parents.get(current)

    @staticmethod
    def _existing_by_name(
        session: Session, campaign_id: str
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for entity_type, model in MODEL_BY_TYPE.items():
            rows = session.scalars(
                select(model)
                .where(model.campaign_id == campaign_id)  # type: ignore[attr-defined]
                .order_by(model.id)  # type: ignore[attr-defined]
            )
            result[entity_type] = {
                PrepImportService._normalize_name(row.name): row  # type: ignore[attr-defined]
                for row in rows
            }
        return result

    @staticmethod
    def _initial_reuse_map(validation: dict[str, Any]) -> dict[str, dict[str, str]]:
        return {
            entity_type: {
                key: entity_id
                for key, entity_id in validation["reference_plan"][entity_type].items()
                if entity_id != "new"
            }
            for entity_type in ENTITY_ORDER
        }

    @staticmethod
    def _create_locations(
        session: Session,
        campaign_id: str,
        draft: PrepDraft,
        refs: dict[str, dict[str, str]],
        created: dict[str, int],
        created_ids: dict[str, list[str]],
    ) -> None:
        pending = {row.key: row for row in draft.locations if row.key not in refs["locations"]}
        while pending:
            ready = [
                row
                for row in pending.values()
                if row.parent_location_key is None
                or row.parent_location_key in refs["locations"]
            ]
            if not ready:
                raise ValueError("location hierarchy could not be resolved")
            for row in ready:
                data = row.model_dump(exclude={"key", "parent_location_key"})
                data["parent_location_id"] = (
                    refs["locations"][row.parent_location_key]
                    if row.parent_location_key is not None
                    else None
                )
                entity = Location(campaign_id=campaign_id, **data)
                session.add(entity)
                session.flush()
                refs["locations"][row.key] = entity.id
                created["locations"] += 1
                created_ids["locations"].append(entity.id)
                pending.pop(row.key)

    @staticmethod
    def _create_npcs(
        session: Session,
        campaign_id: str,
        draft: PrepDraft,
        refs: dict[str, dict[str, str]],
        created: dict[str, int],
        created_ids: dict[str, list[str]],
    ) -> None:
        for row in draft.npcs:
            if row.key in refs["npcs"]:
                continue
            data = row.model_dump(exclude={"key", "location_key"})
            data["location_id"] = (
                refs["locations"][row.location_key] if row.location_key is not None else None
            )
            entity = NPC(campaign_id=campaign_id, **data)
            session.add(entity)
            session.flush()
            refs["npcs"][row.key] = entity.id
            created["npcs"] += 1
            created_ids["npcs"].append(entity.id)

    @staticmethod
    def _create_monsters(
        session: Session,
        campaign_id: str,
        draft: PrepDraft,
        refs: dict[str, dict[str, str]],
        created: dict[str, int],
        created_ids: dict[str, list[str]],
    ) -> None:
        for row in draft.monsters:
            if row.key in refs["monsters"]:
                continue
            data = row.model_dump(exclude={"key"})
            entity = MonsterInstance(campaign_id=campaign_id, **data)
            session.add(entity)
            session.flush()
            refs["monsters"][row.key] = entity.id
            created["monsters"] += 1
            created_ids["monsters"].append(entity.id)

    @staticmethod
    def _create_quests(
        session: Session,
        campaign_id: str,
        draft: PrepDraft,
        refs: dict[str, dict[str, str]],
        created: dict[str, int],
        created_ids: dict[str, list[str]],
    ) -> None:
        npc_by_key = {row.key: row for row in draft.npcs}
        for row in draft.quests:
            if row.key in refs["quests"]:
                continue
            data = row.model_dump(exclude={"key", "giver_npc_key"})
            if row.giver_npc_key is not None:
                data["giver"] = npc_by_key[row.giver_npc_key].name
            entity = Quest(campaign_id=campaign_id, xp_awarded=False, **data)
            session.add(entity)
            session.flush()
            refs["quests"][row.key] = entity.id
            created["quests"] += 1
            created_ids["quests"].append(entity.id)

    @staticmethod
    def _create_scenes(
        session: Session,
        campaign_id: str,
        draft: PrepDraft,
        refs: dict[str, dict[str, str]],
        created: dict[str, int],
        created_ids: dict[str, list[str]],
    ) -> None:
        for row in draft.scenes:
            if row.key not in refs["scenes"]:
                data = row.model_dump(
                    exclude={"key", "location_key", "participants", "grid"}
                )
                data["location_id"] = (
                    refs["locations"][row.location_key]
                    if row.location_key is not None
                    else None
                )
                entity = Scene(campaign_id=campaign_id, **data)
                session.add(entity)
                session.flush()
                refs["scenes"][row.key] = entity.id
                created["scenes"] += 1
                created_ids["scenes"].append(entity.id)
            scene_id = refs["scenes"][row.key]
            if session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id)) is None:
                grid_data = (
                    row.grid.model_dump()
                    if row.grid is not None
                    else {
                        "width": 12,
                        "height": 8,
                        "cell_size_ft": 5,
                        "mode": "exploration",
                        "public_description": row.description,
                        "dm_description": row.notes,
                        "layers_json": {},
                    }
                )
                session.add(SceneGrid(scene_id=scene_id, **grid_data))
            existing = {
                (participant.entity_type, participant.entity_id)
                for participant in session.scalars(
                    select(SceneParticipant).where(SceneParticipant.scene_id == scene_id)
                )
            }
            for participant in row.participants:
                entity_id = refs[
                    "npcs" if participant.entity_type == "npc" else "monsters"
                ][participant.entity_key]
                if (participant.entity_type, entity_id) in existing:
                    continue
                data = participant.model_dump(exclude={"entity_key"})
                data["entity_id"] = entity_id
                session.add(SceneParticipant(scene_id=scene_id, **data))
                existing.add((participant.entity_type, entity_id))

    @staticmethod
    def _create_clues(
        session: Session,
        campaign_id: str,
        draft: PrepDraft,
        refs: dict[str, dict[str, str]],
        created: dict[str, int],
        created_ids: dict[str, list[str]],
    ) -> None:
        for row in draft.clues:
            if row.key in refs["clues"]:
                continue
            data = row.model_dump(exclude={"key", "quest_key"})
            data["quest_id"] = (
                refs["quests"][row.quest_key] if row.quest_key is not None else None
            )
            entity = Clue(campaign_id=campaign_id, source_event_id=None, **data)
            session.add(entity)
            session.flush()
            refs["clues"][row.key] = entity.id
            created["clues"] += 1
            created_ids["clues"].append(entity.id)

    @staticmethod
    def _create_items(
        session: Session,
        campaign_id: str,
        draft: PrepDraft,
        refs: dict[str, dict[str, str]],
        created: dict[str, int],
        created_ids: dict[str, list[str]],
    ) -> None:
        for row in draft.items:
            if row.key in refs["items"]:
                continue
            data = row.model_dump(exclude={"key", "location_key"})
            data["location_id"] = refs["locations"][row.location_key]
            data["owner_character_id"] = None
            data["is_equipped"] = False
            entity = WorldItem(campaign_id=campaign_id, **data)
            session.add(entity)
            session.flush()
            refs["items"][row.key] = entity.id
            created["items"] += 1
            created_ids["items"].append(entity.id)

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _normalize_name(value: str) -> str:
        return " ".join(value.casefold().split())

    @staticmethod
    def _draft_hash(draft: PrepDraft, duplicate_strategy: DuplicateStrategy) -> str:
        payload = {
            "draft": draft.model_dump(mode="json"),
            "duplicate_strategy": duplicate_strategy,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _plan_fingerprint(validation: dict[str, Any]) -> dict[str, Any]:
        return {
            "valid": validation["valid"],
            "errors": validation["errors"],
            "operations": validation["operations"],
            "reference_plan": validation["reference_plan"],
        }

    @classmethod
    def _token(
        cls,
        campaign_id: str,
        draft: PrepDraft,
        duplicate_strategy: DuplicateStrategy,
        validation: dict[str, Any],
        expires_at: datetime,
    ) -> str:
        expires_epoch = int(expires_at.timestamp())
        payload = {
            "campaign_id": campaign_id,
            "draft_hash": cls._draft_hash(draft, duplicate_strategy),
            "expires": expires_epoch,
            "plan": cls._plan_fingerprint(validation),
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"{expires_epoch:x}.{digest}"

    @staticmethod
    def _expires_at(token: str) -> datetime:
        try:
            prefix, digest = token.split(".", 1)
            if len(digest) != 64:
                raise ValueError
            return datetime.fromtimestamp(int(prefix, 16), UTC)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid prep import preview token") from exc
