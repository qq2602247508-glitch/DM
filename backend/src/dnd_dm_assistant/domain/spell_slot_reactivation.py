"""Generic contract for reactivating an inactive, once-per-rest entity.

The contract intentionally models the payment choice separately from the
entity lifecycle and from the spell-slot resource store.  A persistence
consumer can compose it with the existing Resource/Rest/OperationTransaction
transaction without creating a parallel resource system.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

SPELL_SLOT_REACTIVATION_SCHEMA = "spell.slot.reactivation.v1"
REACTIVATION_PAYMENTS = frozenset({"long_rest", "spell_slot_any_level"})
REACTIVATION_EVENTS = frozenset({"activate", "deactivate", "reactivate", "long_rest"})
ReactivationStatus = Literal["inactive", "active"]


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class SpellSlotReactivationSpec:
    """Source-bound contract for one manifestation cycle."""

    entity_binding: str
    source_id: str
    source_fingerprint: str
    activation_limit: int = 1
    spell_slot_resource_prefix: str = "spell_slots_"

    def __post_init__(self) -> None:
        if not _text(self.entity_binding):
            raise ValueError("spell slot reactivation entity_binding is required")
        if not _text(self.source_id):
            raise ValueError("spell slot reactivation source_id is required")
        if not _text(self.source_fingerprint):
            raise ValueError("spell slot reactivation source_fingerprint is required")
        if self.activation_limit != 1:
            raise ValueError("spell slot reactivation activation_limit must be exactly one")
        if not _text(self.spell_slot_resource_prefix):
            raise ValueError("spell slot reactivation resource prefix is required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SPELL_SLOT_REACTIVATION_SCHEMA,
            "entity_binding": self.entity_binding,
            "source_id": self.source_id,
            "source_fingerprint": self.source_fingerprint,
            "activation_limit": self.activation_limit,
            "spell_slot_resource_prefix": self.spell_slot_resource_prefix,
        }


@dataclass(frozen=True, slots=True)
class ReactivationResult:
    state: dict[str, Any]
    replayed: bool = False
    payment: dict[str, Any] | None = None


def _validate_state(state: Mapping[str, Any], spec: SpellSlotReactivationSpec) -> None:
    if _text(state.get("schema")) != SPELL_SLOT_REACTIVATION_SCHEMA:
        raise ValueError("spell slot reactivation state schema is invalid")
    for key in ("entity_binding", "source_id", "source_fingerprint"):
        if _text(state.get(key)) != _text(getattr(spec, key)):
            raise ValueError(f"spell slot reactivation {key} does not match the spec")
    if state.get("status") not in {"inactive", "active"}:
        raise ValueError("spell slot reactivation status is invalid")
    if state.get("activation_limit") != 1:
        raise ValueError("spell slot reactivation activation_limit is invalid")
    if (
        not isinstance(state.get("activation_count"), int)
        or state["activation_count"] not in {0, 1}
    ):
        raise ValueError("spell slot reactivation activation_count is invalid")
    if not isinstance(state.get("reactivation_available"), bool):
        raise ValueError("spell slot reactivation availability is invalid")
    if not isinstance(state.get("version"), int) or state["version"] < 1:
        raise ValueError("spell slot reactivation version is invalid")


def _request_fingerprint(
    spec: SpellSlotReactivationSpec,
    *,
    event: str,
    payment: Mapping[str, Any] | None,
    metadata: Mapping[str, Any] | None,
) -> str:
    return _fingerprint(
        {
            "schema": SPELL_SLOT_REACTIVATION_SCHEMA,
            "spec": spec.as_dict(),
            "event": event,
            "payment": dict(payment or {}),
            "metadata": dict(metadata or {}),
        }
    )


def transition_spell_slot_reactivation(
    spec: SpellSlotReactivationSpec,
    state: Mapping[str, Any] | None,
    *,
    event: str,
    operation_id: str,
    expected_version: int | None = None,
    payment: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ReactivationResult:
    """Apply one activation/payment/rest transition with CAS and replay.

    ``activate`` is free for the first manifestation in a rest cycle.
    ``reactivate`` requires either ``long_rest`` or one concrete
    ``spell_slot_any_level`` payment.  Spell-slot quantity validation and
    debit belong to the existing Resource/SpellEconomy transaction; this
    contract only requires the typed payment receipt.
    """

    event = _text(event).casefold()
    operation_id = _text(operation_id)
    if event not in REACTIVATION_EVENTS:
        raise ValueError("spell slot reactivation event is invalid")
    if not operation_id:
        raise ValueError("spell slot reactivation operation_id is required")
    payment = dict(payment or {})
    request_fp = _request_fingerprint(spec, event=event, payment=payment, metadata=metadata)

    if state is None:
        if event != "activate":
            raise ValueError("spell slot reactivation can only start with activate")
        if expected_version not in (None, 0):
            raise ValueError(
                "spell slot reactivation create expected_version must be empty or zero"
            )
        return ReactivationResult(
            state={
                "schema": SPELL_SLOT_REACTIVATION_SCHEMA,
                "entity_binding": spec.entity_binding,
                "source_id": spec.source_id,
                "source_fingerprint": spec.source_fingerprint,
                "activation_limit": 1,
                "activation_count": 1,
                "reactivation_available": False,
                "status": "active",
                "version": 1,
                "last_operation_id": operation_id,
                "last_operation_fingerprint": request_fp,
                "metadata": dict(metadata or {}),
            }
        )

    current = dict(state)
    _validate_state(current, spec)
    if expected_version != current["version"]:
        raise ValueError(
            f"spell slot reactivation version conflict: expected {expected_version}, "
            f"actual {current['version']}"
        )
    if current.get("last_operation_id") == operation_id:
        if current.get("last_operation_fingerprint") != request_fp:
            raise ValueError("spell slot reactivation replay payload does not match")
        return ReactivationResult(state=current, replayed=True, payment=payment or None)

    status = str(current["status"])
    count = int(current["activation_count"])
    next_available = bool(current["reactivation_available"])
    next_status = status
    next_count = count
    applied_payment: dict[str, Any] | None = None

    if event == "activate":
        if status != "inactive" or not next_available or count >= spec.activation_limit:
            raise ValueError("spell slot reactivation activation is unavailable")
        next_status, next_available = "active", False
        next_count += 1
    elif event == "deactivate":
        if status != "active":
            raise ValueError("spell slot reactivation entity is not active")
        next_status = "inactive"
    elif event == "long_rest":
        next_available, next_count = True, 0
    else:
        if status != "inactive" or next_available:
            raise ValueError("spell slot reactivation payment is not required")
        payment_kind = _text(payment.get("kind"))
        if payment_kind == "long_rest":
            raise ValueError("long_rest payment must use the long_rest event")
        if payment_kind != "spell_slot_any_level":
            raise ValueError("reactivation requires a spell_slot_any_level payment")
        resource_key = _text(payment.get("resource_key"))
        if not resource_key.startswith(spec.spell_slot_resource_prefix):
            raise ValueError("reactivation payment must identify a spell slot resource")
        if payment.get("amount") != 1:
            raise ValueError("reactivation consumes exactly one spell slot")
        slot_level = payment.get("slot_level")
        if (
            not isinstance(slot_level, int)
            or isinstance(slot_level, bool)
            or not 1 <= slot_level <= 9
        ):
            raise ValueError("reactivation spell slot level must be between 1 and 9")
        next_status, next_available = "active", False
        next_count += 1
        applied_payment = {
            "kind": payment_kind,
            "resource_key": resource_key,
            "slot_level": slot_level,
            "amount": 1,
        }

    next_state = {
        **current,
        "status": next_status,
        "activation_count": next_count,
        "reactivation_available": next_available,
        "version": int(current["version"]) + 1,
        "last_operation_id": operation_id,
        "last_operation_fingerprint": request_fp,
        "metadata": dict(metadata or current.get("metadata") or {}),
    }
    return ReactivationResult(state=next_state, payment=applied_payment)


def rollback_spell_slot_reactivation(
    spec: SpellSlotReactivationSpec,
    current: Mapping[str, Any],
    prior: Mapping[str, Any],
    *,
    operation_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """Return the exact prior snapshot after a failed downstream transaction."""

    _validate_state(current, spec)
    _validate_state(prior, spec)
    if current["version"] != expected_version:
        raise ValueError("spell slot reactivation rollback CAS conflict")
    if current.get("last_operation_id") != _text(operation_id):
        raise ValueError("spell slot reactivation rollback operation mismatch")
    if int(prior["version"]) + 1 != int(current["version"]):
        raise ValueError("spell slot reactivation rollback snapshot is not adjacent")
    return dict(prior)
