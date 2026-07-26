from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"
PARSER_VERSION = "1.0.0"


class ContentType(StrEnum):
    RULES = "rules"
    CLASSES = "classes"
    SUBCLASSES = "subclasses"
    SPELLS = "spells"
    MONSTERS = "monsters"
    ITEMS = "items"
    FEATS = "feats"
    BACKGROUNDS = "backgrounds"
    CONDITIONS = "conditions"
    ACTIONS = "actions"
    EQUIPMENT = "equipment"
    UNKNOWN = "unknown"


class Edition(StrEnum):
    EDITION_2014 = "2014"
    EDITION_2024 = "2024"
    EDITION_2025 = "2025"
    LEGACY = "legacy"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Officiality(StrEnum):
    OFFICIAL = "official"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_type: ContentType = ContentType.UNKNOWN
    source_book: str | None = None
    edition: Edition = Edition.UNKNOWN
    officiality: Officiality = Officiality.UNKNOWN
    legacy: bool = False
    warnings: tuple[str, ...] = ()
    warning_counts: dict[str, int] = Field(default_factory=dict)


class NavigationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    aliases: tuple[str, ...] = ()
    url: str | None = None
    canonical_url: str | None = None
    path_hierarchy: tuple[str, ...] = ()
    source_book: str | None = None
    edition: Edition = Edition.UNKNOWN
    officiality: Officiality = Officiality.UNKNOWN
    legacy: bool = False
    content_type: ContentType = ContentType.UNKNOWN
    fragment: str | None = None
    fetchable: bool = False
    warnings: tuple[str, ...] = ()


class SpellFields(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: int | None = Field(default=None, ge=0, le=9)
    school: str | None = None
    classes: tuple[str, ...] = ()
    casting_time: str | None = None
    range: str | None = None
    components: str | None = None
    duration: str | None = None
    damage_expression: str | None = None
    damage_type: str | None = None
    save: str | None = None
    ritual: bool | None = None
    concentration: bool | None = None
    upcast_text: str | None = None


class NormalizedEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    parser_version: str = PARSER_VERSION
    stable_id: str
    name: str
    aliases: tuple[str, ...] = ()
    content_type: ContentType
    source_url: str
    canonical_url: str
    repository_url: str | None = None
    source_revision: str | None = None
    source_ref: str | None = None
    source_relative_path: str | None = None
    source_license: str = "unknown"
    source_book: str | None = None
    edition: Edition
    language: str = "zh-Hans"
    officiality: Officiality
    legacy: bool = False
    heading_path: tuple[str, ...] = ()
    fragment: str | None = None
    content_markdown: str
    content_plain_text: str
    checksum: str
    fetched_at: datetime
    run_id: str
    spell: SpellFields | None = None
    warnings: tuple[str, ...] = ()


class SourceProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_kind: Literal["fixture", "local_snapshot", "github_snapshot", "website"]
    repository_url: str | None = None
    revision: str | None = None
    source_ref: str | None = None
    declared_license: str = "unknown"
    checkout_path: str | None = None


class RejectedUrl(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    reason: str


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    discovered: int = 0
    fetched: int = 0
    parsed: int = 0
    emitted: int = 0
    skipped: int = 0
    failed: int = 0
    duplicates: int = 0
    checksum_changes: int = 0
    elapsed_seconds: float = 0.0
    output_bytes: int = 0
    by_content_type: dict[str, int] = Field(default_factory=dict)
    by_edition: dict[str, int] = Field(default_factory=dict)
    by_officiality: dict[str, int] = Field(default_factory=dict)
    missing_required_metadata: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    warning_counts: dict[str, int] = Field(default_factory=dict)
    errors: tuple[str, ...] = ()
    rejected_urls: tuple[RejectedUrl, ...] = ()


class QualityAccumulator:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.discovered = 0
        self.fetched = 0
        self.parsed = 0
        self.emitted = 0
        self.skipped = 0
        self.failed = 0
        self.duplicates = 0
        self.checksum_changes = 0
        self.elapsed_seconds = 0.0
        self.output_bytes = 0
        self.by_content_type: Counter[str] = Counter()
        self.by_edition: Counter[str] = Counter()
        self.by_officiality: Counter[str] = Counter()
        self.missing: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.rejected: list[RejectedUrl] = []

    def count_entity(self, entity: NormalizedEntity) -> None:
        self.emitted += 1
        self.by_content_type[entity.content_type.value] += 1
        self.by_edition[entity.edition.value] += 1
        self.by_officiality[entity.officiality.value] += 1
        if not entity.name or not entity.canonical_url or not entity.content_markdown:
            self.missing.append(entity.stable_id)
        self.warnings.extend(entity.warnings)

    def build(self) -> QualityReport:
        warning_counts = Counter(self.warnings)
        return QualityReport(
            run_id=self.run_id,
            discovered=self.discovered,
            fetched=self.fetched,
            parsed=self.parsed,
            emitted=self.emitted,
            skipped=self.skipped,
            failed=self.failed,
            duplicates=self.duplicates,
            checksum_changes=self.checksum_changes,
            elapsed_seconds=round(self.elapsed_seconds, 3),
            output_bytes=self.output_bytes,
            by_content_type=dict(sorted(self.by_content_type.items())),
            by_edition=dict(sorted(self.by_edition.items())),
            by_officiality=dict(sorted(self.by_officiality.items())),
            missing_required_metadata=tuple(sorted(set(self.missing))),
            warnings=tuple(sorted(warning_counts)),
            warning_counts=dict(sorted(warning_counts.items())),
            errors=tuple(sorted(self.errors)),
            rejected_urls=tuple(self.rejected),
        )
