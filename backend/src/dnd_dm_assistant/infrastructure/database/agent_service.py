from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.agent import (
    CampaignAIMessage,
    ModelRunRecord,
    ProposalDecision,
    ProposalStatus,
    StateChangeProposal,
    StateOperation,
    StateOperationKind,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.campaign_repository import (
    SqlAlchemyCampaignStateRepository,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import (
    ENTITY_FIELDS,
    ENTITY_MODELS,
    serialize,
)
from dnd_dm_assistant.infrastructure.database.models import (
    AuditLog,
    Campaign,
    CampaignAISession,
    Location,
    ModelRun,
)
from dnd_dm_assistant.infrastructure.database.models import (
    CampaignAIMessage as CampaignAIMessageRow,
)
from dnd_dm_assistant.infrastructure.database.models import (
    StateChangeProposal as ProposalRow,
)


class SqlAlchemyAgentPersistence:
    """Proposal lifecycle and mutation share one SQLAlchemy transaction."""

    def __init__(
        self,
        engine: Engine,
        *,
        failure_hook: Callable[[], None] | None = None,
    ) -> None:
        self.engine = engine
        self._failure_hook = failure_hook

    def create_proposal(
        self,
        campaign_id: str,
        operation: StateOperation,
        *,
        model_name: str,
        request_id: str,
    ) -> StateChangeProposal:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            if operation.entity_id is not None:
                existing = SqlAlchemyCampaignStateRepository(session).get(
                    operation.entity_type, operation.entity_id, campaign_id
                )
                if existing is None:
                    raise StateNotFoundError(f"{operation.entity_type} not found")
                if operation.entity_type == "character":
                    hp = operation.payload.get("hp", existing.hp)
                    max_hp = operation.payload.get("max_hp", existing.max_hp)
                    if hp > max_hp:
                        raise ValueError("hp cannot exceed max_hp")
            self._ensure_related_scope(
                session, operation.entity_type, operation.payload, campaign_id
            )
            row = ProposalRow(
                campaign_id=campaign_id,
                tool_name="update_campaign_state",
                operation=operation.operation.value,
                entity_type=operation.entity_type,
                entity_id=operation.entity_id,
                payload_json=operation.payload,
                expected_version=operation.expected_version,
                reason=operation.reason,
                status=ProposalStatus.PENDING.value,
                created_by_model=model_name,
                request_id=request_id,
            )
            session.add(row)
            session.flush()
            self._audit_decision(session, row, "proposal_create", request_id)
            return _proposal(row)

    def conversation_history(
        self, campaign_id: str, *, limit: int = 12
    ) -> tuple[CampaignAIMessage, ...]:
        bounded_limit = max(1, min(limit, 24))
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            ai_session = session.scalar(
                select(CampaignAISession).where(CampaignAISession.campaign_id == campaign_id)
            )
            if ai_session is None:
                return ()
            rows = list(
                session.scalars(
                    select(CampaignAIMessageRow)
                    .where(CampaignAIMessageRow.session_id == ai_session.id)
                    .order_by(CampaignAIMessageRow.sequence_number.desc())
                    .limit(bounded_limit)
                ).all()
            )
            rows.reverse()
            return tuple(
                CampaignAIMessage.model_validate(
                    {
                        "role": row.role,
                        "content": row.content,
                        "message_kind": row.message_kind,
                        "authoritative": row.authoritative,
                        "created_at": row.created_at,
                    }
                )
                for row in rows
            )

    def append_conversation_turn(
        self,
        campaign_id: str,
        *,
        user_message: str,
        assistant_message: str,
        request_id: str,
    ) -> None:
        user_message = user_message.strip()
        assistant_message = assistant_message.strip()
        if not user_message or not assistant_message:
            raise ValueError("conversation messages must not be blank")
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            ai_session = session.scalar(
                select(CampaignAISession).where(CampaignAISession.campaign_id == campaign_id)
            )
            if ai_session is None:
                ai_session = CampaignAISession(campaign_id=campaign_id)
                session.add(ai_session)
                session.flush()
            last_sequence = session.scalar(
                select(func.max(CampaignAIMessageRow.sequence_number)).where(
                    CampaignAIMessageRow.session_id == ai_session.id
                )
            )
            first_sequence = int(last_sequence or 0) + 1
            session.add_all(
                (
                    CampaignAIMessageRow(
                        session_id=ai_session.id,
                        role="dm",
                        content=user_message[:2_000],
                        message_kind="question",
                        authoritative=False,
                        request_id=request_id,
                        sequence_number=first_sequence,
                    ),
                    CampaignAIMessageRow(
                        session_id=ai_session.id,
                        role="assistant",
                        content=assistant_message[:8_000],
                        message_kind="answer",
                        authoritative=False,
                        request_id=request_id,
                        sequence_number=first_sequence + 1,
                    ),
                )
            )

    def list_proposals(
        self, campaign_id: str, *, status: str = "pending", limit: int = 100
    ) -> tuple[StateChangeProposal, ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            query = (
                select(ProposalRow)
                .where(
                    ProposalRow.campaign_id == campaign_id,
                    ProposalRow.status == ProposalStatus(status).value,
                )
                .order_by(ProposalRow.created_at.asc(), ProposalRow.id.asc())
                .limit(limit)
            )
            return tuple(_proposal(row) for row in session.scalars(query).all())

    def confirm(self, campaign_id: str, proposal_id: str, *, request_id: str) -> ProposalDecision:
        with Session(self.engine) as session, session.begin():
            row = self._get(session, campaign_id, proposal_id)
            if row.status != ProposalStatus.PENDING.value:
                return ProposalDecision(proposal=_proposal(row), already_decided=True)
            operation = _operation(row)
            claimed_at = datetime.now(UTC)
            claimed = session.execute(
                update(ProposalRow)
                .where(
                    ProposalRow.id == proposal_id,
                    ProposalRow.campaign_id == campaign_id,
                    ProposalRow.status == ProposalStatus.PENDING.value,
                    ProposalRow.version == row.version,
                )
                .values(
                    status=ProposalStatus.CONFIRMED.value,
                    decided_at=claimed_at,
                    updated_at=claimed_at,
                    version=row.version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if getattr(claimed, "rowcount", None) != 1:
                session.expire_all()
                current = self._get(session, campaign_id, proposal_id)
                return ProposalDecision(proposal=_proposal(current), already_decided=True)
            session.refresh(row)
            try:
                applied = self._apply(session, campaign_id, operation, request_id)
            except VersionConflict:
                row.status = ProposalStatus.CONFLICT.value
                row.updated_at = datetime.now(UTC)
                self._audit_decision(session, row, "proposal_conflict", request_id)
                session.flush()
                return ProposalDecision(proposal=_proposal(row))
            if self._failure_hook is not None:
                self._failure_hook()
            self._audit_decision(session, row, "proposal_confirm", request_id)
            session.flush()
            return ProposalDecision(proposal=_proposal(row), applied_entity=applied)

    def reject(self, campaign_id: str, proposal_id: str, *, request_id: str) -> ProposalDecision:
        with Session(self.engine) as session, session.begin():
            row = self._get(session, campaign_id, proposal_id)
            if row.status != ProposalStatus.PENDING.value:
                return ProposalDecision(proposal=_proposal(row), already_decided=True)
            decided_at = datetime.now(UTC)
            claimed = session.execute(
                update(ProposalRow)
                .where(
                    ProposalRow.id == proposal_id,
                    ProposalRow.campaign_id == campaign_id,
                    ProposalRow.status == ProposalStatus.PENDING.value,
                    ProposalRow.version == row.version,
                )
                .values(
                    status=ProposalStatus.REJECTED.value,
                    decided_at=decided_at,
                    updated_at=decided_at,
                    version=row.version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if getattr(claimed, "rowcount", None) != 1:
                session.expire_all()
                current = self._get(session, campaign_id, proposal_id)
                return ProposalDecision(proposal=_proposal(current), already_decided=True)
            session.refresh(row)
            self._audit_decision(session, row, "proposal_reject", request_id)
            session.flush()
            return ProposalDecision(proposal=_proposal(row))

    def record_model_run(self, record: ModelRunRecord) -> None:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, record.campaign_id)
            session.add(
                ModelRun(
                    campaign_id=record.campaign_id,
                    request_id=record.request_id,
                    model_role=record.model_role,
                    model_name=record.model_name,
                    prompt_version=record.prompt_version,
                    latency_ms=record.latency_ms,
                    status=record.status.value,
                    error_category=record.error_category,
                )
            )

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _get(session: Session, campaign_id: str, proposal_id: str) -> ProposalRow:
        row = session.scalar(
            select(ProposalRow).where(
                ProposalRow.id == proposal_id, ProposalRow.campaign_id == campaign_id
            )
        )
        if row is None:
            raise StateNotFoundError("proposal not found")
        return row

    def _apply(
        self,
        session: Session,
        campaign_id: str,
        operation: StateOperation,
        request_id: str,
    ) -> dict[str, Any] | None:
        model = ENTITY_MODELS[operation.entity_type]
        values = {
            field: operation.payload[field]
            for field in ENTITY_FIELDS[operation.entity_type]
            if field in operation.payload
        }
        if operation.entity_type == "event" and isinstance(values.get("occurred_at"), str):
            values["occurred_at"] = datetime.fromisoformat(
                values["occurred_at"].replace("Z", "+00:00")
            )
        self._ensure_related_scope(session, operation.entity_type, values, campaign_id)
        if operation.operation is StateOperationKind.CREATE:
            values["campaign_id"] = campaign_id
            entity = model(**values)
            session.add(entity)
            session.flush()
            self._audit_mutation(
                session,
                campaign_id,
                "create",
                operation.entity_type,
                entity.id,
                None,
                entity,
                request_id,
            )
            return serialize(entity)
        entity = SqlAlchemyCampaignStateRepository(session).get(
            operation.entity_type, operation.entity_id or "", campaign_id
        )
        if entity is None:
            raise StateNotFoundError(f"{operation.entity_type} not found")
        expected = operation.expected_version or 0
        actual = int(entity.version)
        if actual != expected:
            raise VersionConflict(operation.entity_type, entity.id, expected, actual)
        before = serialize(entity)
        if operation.operation is StateOperationKind.UPDATE:
            values["version"] = expected + 1
            values["updated_at"] = datetime.now(UTC)
            result = session.execute(
                update(model)
                .where(model.id == entity.id, model.version == expected)
                .values(**values)
            )
            if getattr(result, "rowcount", None) != 1:
                raise VersionConflict(operation.entity_type, entity.id, expected, actual)
            session.refresh(entity)
            self._audit_mutation(
                session,
                campaign_id,
                "update",
                operation.entity_type,
                entity.id,
                before,
                entity,
                request_id,
            )
            return serialize(entity)
        result = session.execute(
            sa_delete(model).where(model.id == entity.id, model.version == expected)
        )
        if getattr(result, "rowcount", None) != 1:
            raise VersionConflict(operation.entity_type, entity.id, expected, actual)
        self._audit_mutation(
            session,
            campaign_id,
            "delete",
            operation.entity_type,
            entity.id,
            before,
            None,
            request_id,
        )
        return None

    @staticmethod
    def _ensure_related_scope(
        session: Session, entity_type: str, data: dict[str, Any], campaign_id: str
    ) -> None:
        if entity_type in {"npc", "event"} and data.get("location_id"):
            location = session.get(Location, data["location_id"])
            if location is None or location.campaign_id != campaign_id:
                raise StateNotFoundError("location not found in campaign")

    @staticmethod
    def _audit_mutation(
        session: Session,
        campaign_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        before: Any,
        after: Any,
        request_id: str,
    ) -> None:
        session.add(
            AuditLog(
                campaign_id=campaign_id,
                actor="dm-confirmed-agent",
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_json=before,
                after_json=serialize(after) if after is not None else None,
                request_id=request_id,
            )
        )

    @staticmethod
    def _audit_decision(session: Session, row: ProposalRow, action: str, request_id: str) -> None:
        before_status = None if action == "proposal_create" else "pending"
        session.add(
            AuditLog(
                campaign_id=row.campaign_id,
                actor="dm",
                action=action,
                entity_type="state_change_proposal",
                entity_id=row.id,
                before_json=None if before_status is None else {"status": before_status},
                after_json={
                    "status": row.status,
                    "entity_type": row.entity_type,
                    "operation": row.operation,
                },
                request_id=request_id,
            )
        )


def _operation(row: ProposalRow) -> StateOperation:
    return StateOperation.model_validate_json(
        json.dumps(
            {
                "operation": row.operation,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "payload": row.payload_json,
                "expected_version": row.expected_version,
                "reason": row.reason,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _proposal(row: ProposalRow) -> StateChangeProposal:
    return StateChangeProposal.model_validate_json(
        json.dumps(
            {
                "id": row.id,
                "campaign_id": row.campaign_id,
                "tool_name": row.tool_name,
                "operation": row.operation,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "payload": row.payload_json,
                "expected_version": row.expected_version,
                "reason": row.reason,
                "status": row.status,
                "created_by_model": row.created_by_model,
                "request_id": row.request_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "decided_at": row.decided_at,
                "version": row.version,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    )
