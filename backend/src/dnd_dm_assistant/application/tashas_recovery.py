# ruff: noqa: E501
"""Second-pass Tasha QA, ItemSpec authoring and semantic/template projections."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.tashas_whole_pack import (
    PACK_ID,
    _heading_anchors,
    _record_id,
    _text,
)
from dnd_dm_assistant.domain.content_ir_status import build_status_layers
from dnd_dm_assistant.domain.item_spec import ItemSpec, compile_item_spec

RECOVERY_DATE = "2026-08-11"


def _source_body(record: Mapping[str, Any], atom: Mapping[str, Any]) -> str:
    markdown = _text(record.get("content_markdown") or record.get("content_plain_text"))
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    fragment = _text(atom.get("source_fragment"))
    if fragment == "page":
        return markdown.strip()
    try:
        line_number = int(fragment)
    except ValueError:
        return markdown.strip()
    anchors = _heading_anchors(markdown, style="any")
    for index, (start, end, _title) in enumerate(anchors):
        if start + 1 != line_number:
            continue
        next_start = anchors[index + 1][0] if index + 1 < len(anchors) else len(lines)
        return "\n".join(lines[end + 1 : next_start]).strip()
    return markdown.strip()


def _rarity(text: str) -> str | None:
    for value in ("传说", "极珍稀", "珍稀", "非普通", "普通"):
        if value in text:
            return value
    return None


def _item_kind(atom: Mapping[str, Any], text: str) -> str:
    if atom.get("content_kind") == "magic_tattoo":
        return "magic_tattoo"
    if "武器" in text:
        return "weapon"
    if "护甲" in text or "盔甲" in text:
        return "armor"
    if "法器" in text or "圣徽" in text or "法术书" in text:
        return "spellcasting_focus"
    if "工具" in text:
        return "tool"
    return "wondrous_item"


def _attunement(text: str) -> tuple[bool, dict[str, Any]]:
    match = re.search(r"需([^\n*，,）)]+)?同调", text)
    if not match and "需同调" not in text:
        return False, {}
    requirement = match.group(1).strip(" ：:（(") if match and match.group(1) else None
    return True, {"required": True, "requirements_text": requirement or "任意生物"}


def _charge_clause(text: str, atom_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    match = re.search(r"(\d+)发充能", text)
    if not match:
        return {}, {}
    maximum = int(match.group(1))
    if "黎明" in text:
        trigger = "dawn"
    elif "长休" in text:
        trigger = "long_rest"
    elif "短休" in text:
        trigger = "short_rest"
    else:
        trigger = "none"
    charges = {
        "maximum": maximum,
        "current": maximum,
        "recovery_trigger": trigger,
        "recovery_amount": "all" if "所有已消耗" in text else None,
    }
    clause = {
        "clause_id": f"{atom_id}:charges",
        "clause_type": "charge",
        "trigger": "item_lifecycle",
        "action_economy": "none",
        "parameters": charges,
        "evidence": {"text": match.group(0)},
    }
    recovery_clause = (
        {
            "clause_id": f"{atom_id}:charge-recovery",
            "clause_type": "charge_recovery",
            "trigger": trigger,
            "action_economy": "none",
            "parameters": {
                "recovery_trigger": trigger,
                "recovery_amount": charges["recovery_amount"],
                "typed_dawn_event_required": trigger == "dawn",
            },
            "evidence": {"text": text[:240]},
        }
        if trigger != "none"
        else {}
    )
    return clause, recovery_clause


def _explicit_resistance(text: str, atom_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resistances: list[dict[str, Any]] = []
    immunities: list[dict[str, Any]] = []
    damage_types = "强酸|寒冷|火焰|力场|闪电|暗蚀|毒素|心灵|光耀|雷鸣|钝击|穿刺|挥砍"
    for match in re.finditer(rf"对(({damage_types})(?:、({damage_types}))*)伤害的抗性", text):
        values = [item for item in re.split(r"、", match.group(1)) if item]
        resistances.append(
            {
                "id": f"{atom_id}:resistance:{len(resistances)+1}",
                "damage_types": values,
                "source_text": match.group(0),
            }
        )
    if "伤害免疫" in text:
        immunities.append(
            {
                "id": f"{atom_id}:immunity:1",
                "scope": "source_text",
                "source_text": "伤害免疫",
                "manual_decision_required": True,
            }
        )
    return resistances, immunities


def _action_clauses(text: str, atom_id: str) -> tuple[list[dict[str, Any]], bool]:
    actions: list[dict[str, Any]] = []
    manual = False
    if not re.search(r"作为一个(?:动作|附赠动作|反应)|用一个(?:动作|附赠动作|反应)", text):
        return actions, manual
    economy = "bonus_action" if "附赠动作" in text else "reaction" if "反应" in text else "action"
    for index, match in enumerate(re.finditer(r"作为一个(动作|附赠动作|反应)|用一个(动作|附赠动作|反应)", text)):
        action_id = f"{atom_id}:action:{index+1}"
        action_text = text[match.start() : match.start() + 320]
        target_policy = (
            "self"
            if re.search(r"对你(?:自己)?|你获得|你可以", action_text)
            else "explicit_target"
            if re.search(r"目标|生物|你可见|距离", action_text)
            else "source_text"
        )
        ambiguous = bool(re.search(r"随机|DM|表格|由你决定|任选", action_text))
        manual = manual or ambiguous
        actions.append(
            {
                "action_id": action_id,
                "action_economy": economy,
                "charge_cost": 1 if "消耗1发" in action_text else 0,
                "target_policy": target_policy,
                "source_excerpt": action_text,
                "manual_review_required": ambiguous,
                "consumer_id": "item.granted_action.v1",
            }
        )
    return actions, manual


def _explicit_spell_identities(text: str) -> list[dict[str, str]]:
    """Extract inline spell identities from an explicit ``施展`` clause.

    The source uses both a singular ``施展*中文**English*法术`` form and a
    list form such as ``施展以下法术：*中文**English*，...``.  The scope is
    anchored after the verb so generic references like ``这道法术`` and class
    spell-list prose remain fail-closed.
    """

    inline_pattern = re.compile(
        r"\*+(?P<localized>[\u3400-\u9fff][^*\n。|]{1,48}?)\*{1,2}"
        r"\s*(?P<english>[A-Z][A-Za-z’'\-\s]{2,}?)\*{1,2}"
        r"(?=\s*(?:法术|[，,。；;|（(]|$))"
    )
    identities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for marker in re.finditer(r"施展", text):
        remainder = text[marker.end() : marker.end() + 1800]
        boundaries = [position for position in (remainder.find("。"), remainder.find("|")) if position >= 0]
        window = remainder[: min(boundaries)] if boundaries else remainder
        for match in inline_pattern.finditer(window):
            localized = re.sub(r"\s+", "", match.group("localized")).strip("* ")
            english = re.sub(r"\s+", " ", match.group("english").strip("* "))
            if (
                not english
                or english.casefold() in {"grappled", "restrained"}
                or any(
                    token in localized
                    for token in (
                        "一道",
                        "下列",
                        "以下",
                        "那道",
                        "该法术",
                        "任意",
                        "任何",
                        "恢复生命值",
                        "德鲁伊",
                        "游侠",
                        "法师",
                        "术士",
                        "邪术师",
                        "牧师",
                        "法术后",
                        "法术对",
                        "某个",
                    )
                )
            ):
                continue
            key = (localized, english)
            if localized and key not in seen:
                seen.add(key)
                identities.append(
                    {
                        "localized_name": localized,
                        "english_name": english,
                        "spell_id": english.casefold().replace(" ", "-") if english else localized,
                    }
                )
    return identities


def item_spec_for_atom(
    atom: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    pack_version: str = f"whole-pack-{RECOVERY_DATE}",
) -> dict[str, Any]:
    """Author one closed ItemSpec from explicit source evidence."""

    body = _source_body(record, atom)
    heading = f"{atom.get('name', '')}\n{body}"
    requires_attunement, attunement_requirements = _attunement(heading)
    charge, recovery = _charge_clause(body, str(atom["atom_id"]))
    resistances, immunities = _explicit_resistance(body, str(atom["atom_id"]))
    actions, action_manual = _action_clauses(body, str(atom["atom_id"]))
    spell_identities = _explicit_spell_identities(body)
    clauses: list[dict[str, Any]] = [
        {
            "clause_id": f"{atom['atom_id']}:equipment",
            "clause_type": "equipment",
            "trigger": "item_lifecycle",
            "action_economy": "none",
            "parameters": {"equipped_slot": "worn" if atom["content_kind"] == "magic_tattoo" else "worn"},
            "evidence": {"source_fragment": atom.get("source_fragment")},
        }
    ]
    if requires_attunement:
        clauses.append(
            {
                "clause_id": f"{atom['atom_id']}:attunement",
                "clause_type": "attunement",
                "trigger": "attunement_confirmed",
                "action_economy": "none",
                "parameters": attunement_requirements,
                "evidence": {"source_text": "需同调"},
            }
        )
    if atom["content_kind"] == "magic_tattoo":
        clauses.append(
            {
                "clause_id": f"{atom['atom_id']}:tattoo-lifecycle",
                "clause_type": "tattoo_lifecycle",
                "trigger": "attunement_confirmed",
                "action_economy": "none",
                "parameters": {
                    "on_attune": "ink_manifestation",
                    "on_unattune": "needle_returns_and_effects_removed",
                },
                "evidence": {"source_text": "针头会化为墨水再变成刺青"},
            }
        )
    for item_clause in (charge, recovery):
        if item_clause:
            clauses.append(item_clause)
    for resistance in resistances:
        clauses.append(
            {
                "clause_id": resistance["id"],
                "clause_type": "resistance",
                "trigger": "equipped_or_attuned",
                "action_economy": "none",
                "parameters": resistance,
                "evidence": {"source_text": resistance["source_text"]},
            }
        )
    for immunity in immunities:
        clauses.append(
            {
                "clause_id": immunity["id"],
                "clause_type": "immunity",
                "trigger": "equipped_or_attuned",
                "action_economy": "none",
                "parameters": immunity,
                "evidence": {"source_text": immunity["source_text"]},
            }
        )
    for action in actions:
        clauses.append(
            {
                "clause_id": action["action_id"],
                "clause_type": "granted_action",
                "trigger": "item_action_requested",
                "action_economy": action["action_economy"],
                "parameters": action,
                "evidence": {"source_excerpt": action["source_excerpt"]},
            }
        )
    spell_context = bool(
        spell_identities
        or re.search(r"施展\s*(?:下列|以下|那道|该法术|一道)法术", body)
    )
    generic_spell_grant = (
        spell_context
        and not spell_identities
        and "恢复生命值的法术" not in body
        and "作为你施展" not in body
    )
    if spell_context:
        clauses.append(
            {
                "clause_id": f"{atom['atom_id']}:spell-grant",
                "clause_type": "granted_spell",
                "trigger": "item_action_requested",
                "action_economy": "action",
                "parameters": {
                    "spell_ids": [item["spell_id"] for item in spell_identities],
                    "spell_identities": spell_identities,
                    "grant_mode": "item_cast",
                    "source_text": body[:360],
                },
                "evidence": {
                    "source_excerpt": body[:360],
                    "manual_review_required": generic_spell_grant,
                },
            }
        )
    manual_review = action_manual or bool(immunities) or generic_spell_grant
    if "恢复生命值" in body and re.search(r"d4|D4|一枚4面", body):
        clauses.append(
            {
                "clause_id": f"{atom['atom_id']}:healing-modifier",
                "clause_type": "passive_modifier",
                "trigger": "healing_spell_while_held",
                "action_economy": "none",
                "parameters": {
                    "modifier_kind": "healing_bonus",
                    "dice": "1d4",
                    "target": "self",
                },
                "evidence": {"source_text": "恢复生命值的法术增加1d4"},
            }
        )
    item_kind = _item_kind(atom, heading)
    spec = {
        "schema_version": "item-ir-1",
        "item_id": f"content.{PACK_ID}.item.{atom['atom_id'].replace(':', '-')}",
        "pack_id": PACK_ID,
        "pack_version": pack_version,
        "namespace": "dnd.tashas.recovery.item",
        "ruleset_version": "2024",
        "name": str(atom.get("name") or ""),
        "localized_name": str(atom.get("localized_name") or atom.get("name") or ""),
        "source_record_id": str(atom["source_record_id"]),
        "source_path": str(atom["source_path"]),
        "source_fragment": str(atom["source_fragment"]),
        "source_fingerprint": str(atom["source_fingerprint"]),
        "source_trust": "authored_ir",
        "item_kind": item_kind,
        "rarity": _rarity(heading),
        "requires_attunement": requires_attunement,
        "attunement_requirements": attunement_requirements,
        "equipped_slot": "worn" if atom["content_kind"] == "magic_tattoo" else None,
        "stack_policy": {"mode": "unique_instance"},
        "consumption_policy": {"mode": "charges" if charge else "persistent"},
        "charges": charge.get("parameters", {}) if charge else {},
        "passive_modifiers": [],
        "granted_actions": actions,
        "granted_spells": spell_identities,
        "triggered_effects": [],
        "damage": None,
        "healing": None,
        "temporary_hp": None,
        "conditions": [],
        "resistances": resistances,
        "immunities": immunities,
        "resource_bindings": [],
        "duration": None,
        "clauses": clauses,
        "evidence": {
            "source_path": atom["source_path"],
            "source_fragment": atom["source_fragment"],
            "source_text_sha256": atom["source_fingerprint"],
            "review_status": "reviewed_explicit_fields_only",
            "manual_review_required": manual_review,
            "reviewed_fields": ["identity", "kind", "rarity", "attunement", "charges", "clause_boundaries"],
            "rejected_inferences": ["unknown_effects", "unresolved_spell_identity", "freeform_targeting"],
        },
    }
    validated = ItemSpec.from_dict(spec, "tashas.item")
    compiled = compile_item_spec(validated)
    spec["review_status"] = "reviewed"
    spec["review_fingerprint"] = validated.fingerprint()
    spec["compile"] = compiled
    spec["manual_review_required"] = manual_review
    spec["status_layers"] = build_status_layers(
        source_identified=True,
        draft=True,
        candidate=True,
        reviewed=True,
        authored_typed_ir=True,
        compile_full=compiled["compile_status"] == "full",
        runtime_preview_full=compiled["runtime_preview_full"],
    )
    return spec


def apply_isolated_runtime_validation(
    catalog: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach isolated-registry evidence without promoting formal production."""

    validated_ids = {
        str(item)
        for item in validation.get("isolated_runtime_validated_ids", [])
    }
    registered_ids = {
        str(item)
        for item in validation.get("registered_production_full_ids", [])
    }
    dm_ids = {str(item) for item in validation.get("dm_assisted_ids", [])}
    result = {str(key): value for key, value in catalog.items()}
    specs: list[dict[str, Any]] = []
    for raw in catalog.get("specs", []):
        spec = dict(raw)
        compile_status = spec.get("compile", {}).get("compile_status") == "full"
        item_id = str(spec.get("item_id") or "")
        spec["status_layers"] = build_status_layers(
            source_identified=True,
            draft=True,
            candidate=True,
            reviewed=spec.get("review_status") == "reviewed",
            authored_typed_ir=True,
            compile_full=compile_status,
            runtime_preview_full=bool(spec.get("compile", {}).get("runtime_preview_full")),
            isolated_runtime_validated=item_id in validated_ids,
            registered_production_full=item_id in registered_ids,
            dm_assisted=item_id in dm_ids,
        )
        specs.append(spec)
    result["specs"] = sorted(specs, key=lambda item: str(item.get("item_id")))
    total = len(specs)
    compile_full = sum(
        item.get("compile", {}).get("compile_status") == "full" for item in specs
    )
    isolated_full = sum(
        item.get("status_layers", {}).get("isolated_runtime_validated") for item in specs
    )
    registered_full = sum(
        item.get("status_layers", {}).get("registered_production_full") for item in specs
    )
    dm_assisted = sum(item.get("status_layers", {}).get("dm_assisted") for item in specs)
    result.update(
        {
            "item_spec_runtime_preview_full": compile_full,
            "isolated_runtime_validated": isolated_full,
            "registered_production_full": registered_full,
            "production_full": registered_full,
            "game_usable": registered_full + dm_assisted,
            "item_spec_compile_full": compile_full,
            "item_spec_compile_only": total - compile_full,
            "rates": {
                "reviewed": (sum(item.get("review_status") == "reviewed" for item in specs) / total) if total else 0.0,
                "typed": 1.0 if total else 0.0,
                "compile_full": compile_full / total if total else 0.0,
                "runtime_preview_full": compile_full / total if total else 0.0,
                "isolated_runtime_validated": isolated_full / total if total else 0.0,
                "registered_production_full": registered_full / total if total else 0.0,
                "production_full": registered_full / total if total else 0.0,
                "game_usable": (registered_full + dm_assisted) / total if total else 0.0,
            },
            "status_layer_semantics": {
                "production_full": "registered_production_full; formal registry only",
                "isolated_runtime_validated": "reloaded isolated pack with generic consumers",
                "game_usable": "registered_production_full + dm_assisted",
            },
            "catalog_fingerprint": __import__("dnd_dm_assistant.domain.item_spec", fromlist=["fingerprint"]).fingerprint(specs),
        }
    )
    return result


def load_item_production_evidence(repo_root: Path, pack_id: str = PACK_ID) -> set[str]:
    """Load only item IDs backed by a persisted production-runtime result.

    The isolated pack remains ``formal_apply=false``.  This separate evidence
    channel mirrors the feature funnel: a real equipment consumer run may
    promote an ItemSpec's registered-production layer, while an isolated
    registry reload alone may only promote ``isolated_runtime_validated``.
    """

    prefix = f"content.{pack_id}.item."
    result: set[str] = set()
    root = repo_root / "data" / "content-ir" / "compiled"
    for path in sorted(root.glob("production-runtime-results*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if value.get("content_kind") != "item":
            continue
        checks = value.get("checks")
        if not isinstance(checks, Mapping) or not all(
            checks.get(key)
            for key in (
                "all_create_preview_confirm_replay",
                "all_typed_consumers",
                "all_item_state_persisted",
                "all_attunement_cas",
            )
        ) or checks.get("name_branch_count") != 0:
            continue
        for raw_id in value.get("production_runtime_full_ids") or []:
            item_id = str(raw_id).strip()
            if item_id.startswith(prefix):
                result.add(item_id)
    return result


def build_item_spec_catalog(
    atoms: Iterable[Mapping[str, Any]],
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    record_by_id = {_record_id(record): record for record in records}
    specs: list[dict[str, Any]] = []
    for atom in atoms:
        if atom.get("content_kind") not in {"magic_item", "magic_tattoo"}:
            continue
        record = record_by_id.get(str(atom.get("source_record_id")))
        if record is None:
            continue
        specs.append(item_spec_for_atom(atom, record))
    specs.sort(key=lambda item: str(item["item_id"]))
    compile_counts: dict[str, int] = {}
    for spec in specs:
        status = str(spec["compile"]["compile_status"])
        compile_counts[status] = compile_counts.get(status, 0) + 1
    thresholds = {
        "reviewed": 0.80,
        "typed": 0.70,
        "compile_full": 0.65,
        "production_full": 0.45,
        "game_usable": 0.60,
    }
    compile_full = sum(item["compile"]["compile_status"] == "full" for item in specs)
    rates = {
        "reviewed": (sum(item.get("review_status") == "reviewed" for item in specs) / len(specs)) if specs else 0.0,
        "typed": (len(specs) / len(specs)) if specs else 0.0,
        "compile_full": compile_full / len(specs) if specs else 0.0,
        "runtime_preview_full": compile_full / len(specs) if specs else 0.0,
        "isolated_runtime_validated": 0.0,
        "registered_production_full": 0.0,
        "production_full": 0.0,
        "game_usable": 0.0,
    }
    return {
        "schema_version": "tashas-item-spec-catalog-1",
        "pack_id": PACK_ID,
        "item_spec_total": len(specs),
        "item_spec_reviewed": sum(item.get("review_status") == "reviewed" for item in specs),
        "item_spec_typed": len(specs),
        "item_spec_compile_full": sum(item["compile"]["compile_status"] == "full" for item in specs),
        "item_spec_compile_only": sum(item["compile"]["compile_status"] == "partial" for item in specs),
        "compile_status_counts": dict(sorted(compile_counts.items())),
        "item_spec_runtime_preview_full": compile_full,
        "isolated_runtime_validated": 0,
        "registered_production_full": 0,
        "production_full": 0,
        "game_usable": 0,
        "requires_dm": sum(bool(item.get("manual_review_required")) for item in specs),
        "name_branch_count": 0,
        "thresholds": {
            **thresholds,
            "isolated_runtime_validated": thresholds["compile_full"],
            "registered_production_full": thresholds["production_full"],
        },
        "rates": rates,
        "threshold_gate": False,
        "status_layer_semantics": {
            "production_full": "registered_production_full; formal registry only",
            "isolated_runtime_validated": "not inferred from compile; requires isolated registry reload",
            "game_usable": "registered_production_full + dm_assisted",
        },
        "specs": specs,
        "catalog_fingerprint": __import__("dnd_dm_assistant.domain.item_spec", fromlist=["fingerprint"]).fingerprint(specs),
    }


_TEMPLATE_CONTRACT_FIELDS = (
    "content_kind",
    "grant_shape",
    "choice_shape",
    "action_economy",
    "trigger",
    "resource_recovery",
    "target",
    "attack_save",
    "success_failure",
    "damage_healing",
    "condition",
    "duration",
    "movement",
    "summon",
    "spell_grant",
    "modifier",
    "equipment",
    "attunement",
    "charge",
    "scaling",
    "persistence",
    "runtime_consumer",
    "dm_adjudication",
)


def build_template_catalog(
    atoms: Iterable[Mapping[str, Any]],
    clusters: Mapping[str, Any],
    item_catalog: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish generic templates and their conservative unlock evidence.

    A template is an interface, not a claim that prose is executable.  The
    unlock count only includes fully compiled, typed evidence; an unknown
    contract field keeps the template blocked even when many atoms look
    similar.
    """

    rows = list(atoms)
    item_specs = list(item_catalog.get("specs") or ())
    compiled_items = [item for item in item_specs if item.get("compile", {}).get("compile_status") == "full"]
    definitions = [
        ("feature.grant.fixed", "feature", "grant", ("class_feature", "subclass_feature"), "advancement.feature_grant"),
        ("feature.grant.level_gated", "feature", "grant", ("class_feature", "subclass_feature"), "advancement.level_gate"),
        ("feature.grant.spell_fixed", "feature", "spell_grant", ("class_feature", "subclass_feature"), "advancement.spell"),
        ("feature.grant.spell_expanded", "feature", "spell_grant", ("class_feature", "subclass_feature", "optional_class_feature"), "advancement.spell_list"),
        ("feature.resource.pool", "feature", "resource", ("class_feature", "subclass_feature"), "advancement.resource"),
        ("feature.resource.short_rest", "feature", "resource_recovery", ("class_feature", "subclass_feature"), "rest.short"),
        ("feature.resource.long_rest", "feature", "resource_recovery", ("class_feature", "subclass_feature"), "rest.long"),
        ("feature.proficiency.grant", "feature", "proficiency", ("class_feature", "subclass_feature", "feat"), "advancement.proficiency"),
        ("feature.proficiency.replacement", "feature", "choice", ("class_feature", "subclass_feature", "feat"), "advancement.choice"),
        ("feature.modifier.passive", "feature", "modifier", ("class_feature", "subclass_feature", "feat"), "combat.passive"),
        ("feature.resistance.immunity", "feature", "defense", ("class_feature", "subclass_feature", "feat"), "combat.defense"),
        ("feature.choice.mode", "feature", "choice", ("class_feature", "subclass_feature", "feat", "invocation", "infusion"), "advancement.choice"),
        ("feature.choice.replacement", "feature", "choice", ("class_feature", "subclass_feature", "feat", "maneuver"), "advancement.replacement"),
        ("feature.action.grant", "feature", "action", ("class_feature", "subclass_feature", "feat", "maneuver"), "combat.feature_action"),
        ("feature.triggered.modifier", "feature", "trigger", ("class_feature", "subclass_feature", "feat"), "combat.trigger"),
        ("feature.companion.profile", "feature", "summon", ("companion_profile",), "entity.companion"),
        ("feature.summon.profile", "feature", "summon", ("subclass_feature", "companion_profile"), "entity.summon"),
        ("feature.scaling.die", "feature", "scaling", ("class_feature", "subclass_feature"), "advancement.scaling"),
        ("feature.once_per_turn", "feature", "trigger", ("class_feature", "subclass_feature", "feat"), "combat.trigger"),
        ("option.feat.prereq", "option", "choice", ("feat",), "advancement.feat"),
        ("option.maneuver.choice", "option", "choice", ("maneuver",), "combat.maneuver"),
        ("option.invocation.prereq", "option", "choice", ("invocation",), "advancement.invocation"),
        ("option.infusion.choice", "option", "choice", ("infusion",), "advancement.infusion"),
        ("item.passive", "item", "equipment", ("magic_item", "magic_tattoo"), "item.equipment_modifier.v1"),
        ("item.attunement", "item", "attunement", ("magic_item", "magic_tattoo"), "item.attunement.v1"),
        ("item.charges", "item", "charge", ("magic_item", "magic_tattoo"), "item.charge_resource.v1"),
        ("item.action", "item", "action", ("magic_item", "magic_tattoo"), "item.granted_action.v1"),
        ("item.tattoo.lifecycle", "item", "tattoo_lifecycle", ("magic_tattoo",), "item.attunement.v1"),
    ]
    existing_matches = Counter(
        str(item.get("matched_template_id") or "")
        for item in rows
        if item.get("matched_template_id")
    )
    catalog: list[dict[str, Any]] = []
    for template_id, kind, grant_shape, kinds, consumer in definitions:
        matching_atoms = [item for item in rows if item.get("content_kind") in kinds]
        if kind == "item":
            evidence = [str(item["item_id"]) for item in compiled_items if (
                template_id == "item.passive"
                or template_id == "item.attunement" and any(cl.get("clause_type") in {"attunement", "tattoo_lifecycle"} for cl in item.get("clauses", []))
                or template_id == "item.charges" and any(cl.get("clause_type") == "charge" for cl in item.get("clauses", []))
                or template_id == "item.action" and any(cl.get("clause_type") == "granted_action" for cl in item.get("clauses", []))
                or template_id == "item.tattoo.lifecycle" and item.get("item_kind") == "magic_tattoo"
            )]
        else:
            evidence = [
                str(item.get("atom_id"))
                for item in matching_atoms
                if item.get("migration_status") in {"production_full", "dm_assisted", "compile_only"}
                and not any(
                    "unknown" in str(value)
                    for value in (clusters.get("clusters") or [{}])[0]
                    .get("exact_contract_signature", {})
                    .values()
                )
            ]
        unlock_count = len(evidence)
        catalog.append(
            {
                "template_id": template_id,
                "template_kind": kind,
                "contract_signature": {field: (grant_shape if field == "grant_shape" else "explicit_or_reviewed") for field in _TEMPLATE_CONTRACT_FIELDS},
                "runtime_consumer": consumer,
                "candidate_count": len(matching_atoms),
                "evidence_ids": sorted(evidence)[:100],
                "unlock_count": unlock_count,
                "unlock_gate": {
                    "minimum_cluster_content": 8,
                    "minimum_complete_unlock": 5,
                    "complete_contract_required": True,
                    "status": "unlocked" if unlock_count >= 5 else "blocked",
                },
                "existing_template_match_count": existing_matches.get(template_id, 0),
                "manual_boundary": "unknown clauses remain manual; no name dispatch",
            }
        )
    return {
        "schema_version": "tashas-template-catalog-II-1",
        "pack_id": PACK_ID,
        "template_total": len(catalog),
        "new_template_total": len(catalog),
        "minimum_required": 15,
        "cluster_count": int(clusters.get("cluster_count") or 0),
        "templates": catalog,
        "unlocked_template_total": sum(item["unlock_gate"]["status"] == "unlocked" for item in catalog),
        "catalog_fingerprint": __import__("dnd_dm_assistant.domain.item_spec", fromlist=["fingerprint"]).fingerprint(catalog),
    }


def build_feature_option_batch(
    atoms: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
    reviews: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Report the reviewed feature/option batch without inflating typed IR."""

    kinds = {"class_feature", "subclass_feature", "optional_class_feature", "feat", "maneuver", "invocation", "infusion", "character_option", "companion_profile"}
    rows = [item for item in atoms if item.get("executable_candidate") and item.get("content_kind") in kinds]
    candidate_by_id = {str(item["atom_id"]): item for item in candidates}
    review_by_id = {str(item["atom_id"]): item for item in reviews}
    typed = [item for item in rows if item.get("typed_content_ids")]
    production = [item for item in rows if item.get("migration_status") == "production_full"]
    dm = [item for item in rows if item.get("migration_status") == "dm_assisted"]
    return {
        "schema_version": "tashas-feature-option-batch-I-1",
        "pack_id": PACK_ID,
        "atom_total": len(rows),
        "reviewed_total": sum(str(review_by_id.get(str(item["atom_id"]), {}).get("review_status")) in {"accepted", "accepted_with_edits", "manual_boundary"} for item in rows),
        "typed_total": len(typed),
        "compile_full_total": sum(item.get("migration_status") in {"production_full", "dm_assisted", "compile_only"} for item in rows),
        "production_full_total": len(production),
        "dm_assisted_total": len(dm),
        "manual_total": sum(item.get("migration_status") == "manual_authoring" for item in rows),
        "by_kind": dict(sorted(Counter(str(item.get("content_kind")) for item in rows).items())),
        "review_blocker_counts": dict(sorted(Counter(str(candidate_by_id.get(str(item["atom_id"]), {}).get("match_status")) for item in rows).items())),
        "thresholds": {"reviewed": 120, "typed": 100, "compile_full": 80, "production_full": 50, "dm_assisted": 10},
        "gate_status": "partial",
        "source_of_truth": "tashas-content-atom-catalog-II plus authored Typed IR provenance",
    }
