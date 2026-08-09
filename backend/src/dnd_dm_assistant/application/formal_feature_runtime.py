"""Bridge from persisted feature grants to authored Feature IR runtime blocks."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.formal_feature_specs import (
    formal_feature_spec_for_definition,
)


@lru_cache(maxsize=64)
def _compiler() -> FeatureCompiler:
    return FeatureCompiler(status_authority="compiler")


def authored_ir_runtime_definition(
    definition: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return a production runtime definition when a grant has authored IR."""

    spec = formal_feature_spec_for_definition(definition)
    if spec is None:
        return None
    # verified_mapping entries are intentionally audited against an existing
    # typed runtime registry.  They carry IR fingerprints and source trust,
    # but the registry remains the production authority until a materializer
    # projection is proven field-for-field equivalent.
    if spec.source_trust != "authored_ir":
        return None
    result = _compiler().compile(spec)
    if result.compile_status != "full":
        return None
    return materialize_runtime_definition(spec, result, catalog=_compiler().catalog)
