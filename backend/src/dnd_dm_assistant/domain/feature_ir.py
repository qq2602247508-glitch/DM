"""Versioned, closed-world intermediate representation for feature automation.

The IR is deliberately data-only.  It describes what a feature needs; it does
not contain Python, import paths, expressions, or executable callbacks.  The
compiler resolves every effect through the capability catalog before a
feature can be considered executable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

FEATURE_IR_SCHEMA_VERSION = "feature-ir-1"
FEATURE_SOURCE_TRUSTS = frozenset(
    {"authored_ir", "verified_mapping", "generated_draft", "unstructured_source", "unverified"}
)


class FeatureIRValidationError(ValueError):
    """Raised when a feature manifest violates the closed IR schema."""


def _require_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeatureIRValidationError(f"{path} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, path)


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FeatureIRValidationError(f"{path} must be an object")
    return {str(key): value[key] for key in value}


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise FeatureIRValidationError(f"{path} must be an array")
    return value


def _strict_keys(value: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FeatureIRValidationError(f"{path} contains unknown fields: {', '.join(unknown)}")


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class EffectSpec:
    operator: str
    parameters: dict[str, Any]

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"operator", "parameters"})

    @classmethod
    def from_dict(cls, value: object, path: str) -> EffectSpec:
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        operator = _require_string(data.get("operator"), f"{path}.operator")
        parameters = _mapping(data.get("parameters", {}), f"{path}.parameters")
        return cls(operator=operator, parameters=parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "parameters": _jsonable(self.parameters),
        }


@dataclass(frozen=True)
class ConditionSpec:
    kind: str
    parameters: dict[str, Any]

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"kind", "parameters"})

    @classmethod
    def from_dict(cls, value: object, path: str) -> ConditionSpec:
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        kind = _require_string(data.get("kind"), f"{path}.kind")
        parameters = _mapping(data.get("parameters", {}), f"{path}.parameters")
        return cls(kind=kind, parameters=parameters)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "parameters": _jsonable(self.parameters)}


@dataclass(frozen=True)
class InputSpec:
    key: str
    kind: str
    parameters: dict[str, Any]

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"key", "kind", "parameters"})

    @classmethod
    def from_dict(cls, value: object, path: str) -> InputSpec:
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        key = _require_string(data.get("key"), f"{path}.key")
        kind = _require_string(data.get("kind"), f"{path}.kind")
        parameters = _mapping(data.get("parameters", {}), f"{path}.parameters")
        return cls(key=key, kind=kind, parameters=parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "parameters": _jsonable(self.parameters),
        }


@dataclass(frozen=True)
class ResourceSpec:
    key: str
    operation: str
    amount: object | None
    parameters: dict[str, Any]

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"key", "operation", "amount", "parameters"})

    @classmethod
    def from_dict(cls, value: object, path: str) -> ResourceSpec:
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        key = _require_string(data.get("key"), f"{path}.key")
        operation = _require_string(data.get("operation"), f"{path}.operation")
        parameters = _mapping(data.get("parameters", {}), f"{path}.parameters")
        return cls(
            key=key,
            operation=operation,
            amount=data.get("amount"),
            parameters=parameters,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "operation": self.operation,
            "amount": _jsonable(self.amount),
            "parameters": _jsonable(self.parameters),
        }


@dataclass(frozen=True)
class TargetSpec:
    kind: str
    parameters: dict[str, Any]

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"kind", "parameters"})

    @classmethod
    def from_dict(cls, value: object | None, path: str) -> TargetSpec | None:
        if value is None:
            return None
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        kind = _require_string(data.get("kind"), f"{path}.kind")
        parameters = _mapping(data.get("parameters", {}), f"{path}.parameters")
        return cls(kind=kind, parameters=parameters)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "parameters": _jsonable(self.parameters)}


@dataclass(frozen=True)
class ClauseSpec:
    clause_id: str
    trigger: str
    conditions: tuple[ConditionSpec, ...]
    activation: str
    action_economy: str
    resource_costs: tuple[ResourceSpec, ...]
    resource_recovery: tuple[ResourceSpec, ...]
    required_inputs: tuple[InputSpec, ...]
    targeting: TargetSpec | None
    effects: tuple[EffectSpec, ...]
    duration: object | None
    expiry: object | None
    stacking: object | None
    frequency: object | None
    persistence: object | None
    visibility: object | None
    audit: dict[str, Any]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "clause_id",
            "trigger",
            "conditions",
            "activation",
            "action_economy",
            "resource_costs",
            "resource_recovery",
            "required_inputs",
            "targeting",
            "effects",
            "duration",
            "expiry",
            "stacking",
            "frequency",
            "persistence",
            "visibility",
            "audit",
        }
    )

    @classmethod
    def from_dict(cls, value: object, path: str) -> ClauseSpec:
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        clause_id = _require_string(data.get("clause_id"), f"{path}.clause_id")
        trigger = _require_string(data.get("trigger"), f"{path}.trigger")
        activation = _require_string(data.get("activation", "automatic"), f"{path}.activation")
        action_economy = _require_string(
            data.get("action_economy", "none"), f"{path}.action_economy"
        )

        def parse_entries(
            key: str,
            factory: Any,
        ) -> tuple[Any, ...]:
            values = _list(data.get(key, []), f"{path}.{key}")
            return tuple(
                factory(item, f"{path}.{key}[{index}]") for index, item in enumerate(values)
            )

        effects = parse_entries("effects", EffectSpec.from_dict)
        if not effects:
            raise FeatureIRValidationError(f"{path}.effects must contain at least one effect")
        return cls(
            clause_id=clause_id,
            trigger=trigger,
            conditions=parse_entries("conditions", ConditionSpec.from_dict),
            activation=activation,
            action_economy=action_economy,
            resource_costs=parse_entries("resource_costs", ResourceSpec.from_dict),
            resource_recovery=parse_entries("resource_recovery", ResourceSpec.from_dict),
            required_inputs=parse_entries("required_inputs", InputSpec.from_dict),
            targeting=TargetSpec.from_dict(data.get("targeting"), f"{path}.targeting"),
            effects=effects,
            duration=data.get("duration"),
            expiry=data.get("expiry"),
            stacking=data.get("stacking"),
            frequency=data.get("frequency"),
            persistence=data.get("persistence"),
            visibility=data.get("visibility"),
            audit=_mapping(data.get("audit", {}), f"{path}.audit"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "trigger": self.trigger,
            "conditions": [item.to_dict() for item in self.conditions],
            "activation": self.activation,
            "action_economy": self.action_economy,
            "resource_costs": [item.to_dict() for item in self.resource_costs],
            "resource_recovery": [item.to_dict() for item in self.resource_recovery],
            "required_inputs": [item.to_dict() for item in self.required_inputs],
            "targeting": self.targeting.to_dict() if self.targeting else None,
            "effects": [item.to_dict() for item in self.effects],
            "duration": _jsonable(self.duration),
            "expiry": _jsonable(self.expiry),
            "stacking": _jsonable(self.stacking),
            "frequency": _jsonable(self.frequency),
            "persistence": _jsonable(self.persistence),
            "visibility": _jsonable(self.visibility),
            "audit": _jsonable(self.audit),
        }


@dataclass(frozen=True)
class FeatureSpec:
    schema_version: str
    feature_id: str
    namespace: str
    pack_id: str
    pack_version: str
    ruleset_version: str
    source_record_id: str
    source_name: str
    source_trust: str
    localized_names: dict[str, str]
    class_name: str | None
    subclass_name: str | None
    level: int | None
    source_completeness: str
    clauses: tuple[ClauseSpec, ...]
    dependencies: tuple[str, ...]
    compatibility: dict[str, Any]
    source_path: str | None = None
    source_book: str | None = None
    source_fingerprint: str | None = None
    review_status: str | None = None
    reviewed_by: str | None = None
    reviewed_fields: tuple[str, ...] = ()
    source_evidence: dict[str, Any] = field(default_factory=dict)
    clause_boundaries: dict[str, Any] = field(default_factory=dict)
    manual_decisions: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    compiler_fingerprint: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "feature_id",
            "namespace",
            "pack_id",
            "pack_version",
            "ruleset_version",
            "source_record_id",
            "source_name",
            "source_trust",
            "localized_names",
            "class_name",
            "subclass_name",
            "level",
            "source_completeness",
            "clauses",
            "dependencies",
            "compatibility",
            "source_path",
            "source_book",
            "source_fingerprint",
            "review_status",
            "reviewed_by",
            "reviewed_fields",
            "source_evidence",
            "clause_boundaries",
            "manual_decisions",
            "evidence",
            "compiler_fingerprint",
        }
    )
    _SOURCE_COMPLETENESS: ClassVar[frozenset[str]] = frozenset(
        {"complete", "incomplete", "unstructured"}
    )

    @classmethod
    def from_dict(cls, value: object, path: str = "feature") -> FeatureSpec:
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        schema_version = _require_string(data.get("schema_version"), f"{path}.schema_version")
        if schema_version != FEATURE_IR_SCHEMA_VERSION:
            raise FeatureIRValidationError(
                f"{path}.schema_version {schema_version!r} is unsupported"
            )
        feature_id = _require_string(data.get("feature_id"), f"{path}.feature_id")
        namespace = _require_string(data.get("namespace"), f"{path}.namespace")
        pack_id = _require_string(data.get("pack_id"), f"{path}.pack_id")
        pack_version = _require_string(data.get("pack_version"), f"{path}.pack_version")
        ruleset_version = _require_string(data.get("ruleset_version"), f"{path}.ruleset_version")
        source_record_id = _require_string(data.get("source_record_id"), f"{path}.source_record_id")
        source_name = _require_string(data.get("source_name"), f"{path}.source_name")
        source_trust = _require_string(
            data.get("source_trust", "unverified"), f"{path}.source_trust"
        )
        if source_trust not in FEATURE_SOURCE_TRUSTS:
            raise FeatureIRValidationError(f"{path}.source_trust {source_trust!r} is unsupported")
        localized_raw = _mapping(data.get("localized_names", {}), f"{path}.localized_names")
        localized_names = {
            _require_string(key, f"{path}.localized_names.key"): _require_string(
                item, f"{path}.localized_names[{key}]"
            )
            for key, item in localized_raw.items()
        }
        level = data.get("level")
        if level is not None and (not isinstance(level, int) or isinstance(level, bool)):
            raise FeatureIRValidationError(f"{path}.level must be an integer or null")
        source_completeness = _require_string(
            data.get("source_completeness"), f"{path}.source_completeness"
        )
        if source_completeness not in cls._SOURCE_COMPLETENESS:
            raise FeatureIRValidationError(
                f"{path}.source_completeness {source_completeness!r} is unsupported"
            )
        raw_clauses = _list(data.get("clauses"), f"{path}.clauses")
        if not raw_clauses:
            raise FeatureIRValidationError(f"{path}.clauses must contain at least one clause")
        clauses = tuple(
            ClauseSpec.from_dict(item, f"{path}.clauses[{index}]")
            for index, item in enumerate(raw_clauses)
        )
        clause_ids = [item.clause_id for item in clauses]
        if len(set(clause_ids)) != len(clause_ids):
            raise FeatureIRValidationError(f"{path}.clauses contains duplicate clause_id")
        raw_dependencies = _list(data.get("dependencies", []), f"{path}.dependencies")
        dependencies = tuple(
            _require_string(item, f"{path}.dependencies[{index}]")
            for index, item in enumerate(raw_dependencies)
        )
        reviewed_fields_raw = _list(data.get("reviewed_fields", []), f"{path}.reviewed_fields")
        reviewed_fields = tuple(
            _require_string(item, f"{path}.reviewed_fields[{index}]")
            for index, item in enumerate(reviewed_fields_raw)
        )
        return cls(
            schema_version=schema_version,
            feature_id=feature_id,
            namespace=namespace,
            pack_id=pack_id,
            pack_version=pack_version,
            ruleset_version=ruleset_version,
            source_record_id=source_record_id,
            source_name=source_name,
            source_trust=source_trust,
            localized_names=localized_names,
            class_name=_optional_string(data.get("class_name"), f"{path}.class_name"),
            subclass_name=_optional_string(data.get("subclass_name"), f"{path}.subclass_name"),
            level=level,
            source_completeness=source_completeness,
            clauses=clauses,
            dependencies=dependencies,
            compatibility=_mapping(data.get("compatibility", {}), f"{path}.compatibility"),
            source_path=_optional_string(data.get("source_path"), f"{path}.source_path"),
            source_book=_optional_string(data.get("source_book"), f"{path}.source_book"),
            source_fingerprint=_optional_string(
                data.get("source_fingerprint"), f"{path}.source_fingerprint"
            ),
            review_status=_optional_string(data.get("review_status"), f"{path}.review_status"),
            reviewed_by=_optional_string(data.get("reviewed_by"), f"{path}.reviewed_by"),
            reviewed_fields=reviewed_fields,
            source_evidence=_mapping(data.get("source_evidence", {}), f"{path}.source_evidence"),
            clause_boundaries=_mapping(
                data.get("clause_boundaries", {}), f"{path}.clause_boundaries"
            ),
            manual_decisions=_mapping(
                data.get("manual_decisions", {}), f"{path}.manual_decisions"
            ),
            evidence=tuple(
                _require_string(item, f"{path}.evidence[{index}]")
                for index, item in enumerate(
                    _list(data.get("evidence", []), f"{path}.evidence")
                )
            ),
            compiler_fingerprint=_optional_string(
                data.get("compiler_fingerprint"), f"{path}.compiler_fingerprint"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "namespace": self.namespace,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "ruleset_version": self.ruleset_version,
            "source_record_id": self.source_record_id,
            "source_name": self.source_name,
            "source_trust": self.source_trust,
            "localized_names": _jsonable(self.localized_names),
            "class_name": self.class_name,
            "subclass_name": self.subclass_name,
            "level": self.level,
            "source_completeness": self.source_completeness,
            "clauses": [item.to_dict() for item in self.clauses],
            "dependencies": list(self.dependencies),
            "compatibility": _jsonable(self.compatibility),
            "source_path": self.source_path,
            "source_book": self.source_book,
            "source_fingerprint": self.source_fingerprint,
            "review_status": self.review_status,
            "reviewed_by": self.reviewed_by,
            "reviewed_fields": list(self.reviewed_fields),
            "source_evidence": _jsonable(self.source_evidence),
            "clause_boundaries": _jsonable(self.clause_boundaries),
            "manual_decisions": _jsonable(self.manual_decisions),
            "evidence": list(self.evidence),
            "compiler_fingerprint": self.compiler_fingerprint,
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def feature_spec_from_dict(value: object, path: str = "feature") -> FeatureSpec:
    """Parse one feature without permitting unknown schema fields."""

    return FeatureSpec.from_dict(value, path)


def canonical_json(value: object) -> str:
    """Stable JSON used by compiler and importer fingerprints."""

    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
