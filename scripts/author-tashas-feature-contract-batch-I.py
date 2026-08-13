# ruff: noqa: N999
"""Author the first explicit Tasha Feature/Option semantic-contract batch.

This is a source-bound authoring script, not a keyword-to-operator converter.
Every entry below names one existing Content Atom and supplies the reviewed
clause/operator mapping.  The script copies provenance from that atom, embeds
the bounded source excerpt, parses the result through FeatureSpec and runs the
closed FeatureCompiler before writing the deterministic JSON asset.

The assets intentionally live under ``authored/round-II`` without a leaf
manifest.  The normal whole-pack migration discovers them by provenance, while
the existing six-manifest regression corpus remains unchanged until this
isolated batch has its own runtime registry and acceptance gate.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from dnd_dm_assistant.application.content_ir_workbench import (
    COMPILER_FINGERPRINT,
    load_records,
)
from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.application.tashas_recovery import _source_body
from dnd_dm_assistant.application.tashas_whole_pack import (
    _matches_typed,
    build_migration,
    select_source_records,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

PACK_ID = "tashas-cauldron"
PACK_VERSION = "source-7011166c19bd"
SOURCE_BOOK = "塔莎的万事坩埚"
RULESET_VERSION = "2014"
REVIEWER = "codex-manual-review-2026-08-12-round-II"
OUTPUT_ROOT = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I"
REPORT_PATH = ROOT / "reports/tashas-feature-contract-batch-I-2026-08-12.json"


def effect(operator: str, **parameters: Any) -> dict[str, Any]:
    return {"operator": operator, "parameters": parameters}


def clause(
    clause_id: str,
    effects: list[dict[str, Any]],
    *,
    trigger: str = "advancement_confirmed",
    activation: str = "automatic",
    action_economy: str = "none",
    targeting: dict[str, Any] | None = None,
    duration: str | None = "advancement_persistent",
    source_boundary: str | None = None,
) -> dict[str, Any]:
    # Player choice belongs to the action-economy/input boundary.  The current
    # closed operators materialize the clause itself automatically; using
    # ``explicit_player_choice`` as the activation value would incorrectly
    # reject otherwise supported resource/window contracts.
    if activation == "explicit_player_choice":
        activation = "automatic"
    return {
        "clause_id": clause_id,
        "trigger": trigger,
        "conditions": [],
        "activation": activation,
        "action_economy": action_economy,
        "resource_costs": [],
        "resource_recovery": [],
        "required_inputs": [],
        "targeting": targeting or {"kind": "self", "parameters": {}},
        "effects": effects,
        "duration": duration,
        "expiry": None,
        "stacking": None,
        "frequency": None,
        "persistence": "character.feature_runtime",
        "visibility": "owner",
        "audit": {
            "reviewed_by": REVIEWER,
            "source": "authored_ir",
            "source_boundary": source_boundary or clause_id,
        },
    }


MANIFEST_MIND_BOUNDARIES = {
    "activation-source-and-initial-placement": {
        "source_fragment": "27:activation",
        "source_excerpt": "持有觉醒法术书；以附赠动作显现为微型灵体物件，位于距离你60尺以内且未被占据的所选空间。",
    },
    "spectral-object-form": {
        "source_fragment": "27:form",
        "source_excerpt": "灵体意识无形、不占据空间，周围半径10尺发出微光，并可呈现为灵体卷宗、文字摞或历史学者。",
    },
    "entity-senses": {
        "source_fragment": "27:senses",
        "source_excerpt": "显现时能够听音视物，并具有60尺黑暗视觉。",
    },
    "telepathic-sharing": {
        "source_fragment": "27:telepathy",
        "source_excerpt": "用心灵感应将它所看见和听到的信息分享给你，无需动作。",
    },
    "remote-spell-origin": {
        "source_fragment": "27:remote-origin",
        "source_excerpt": "你在自己的回合内施放法师法术时，可以使用灵体意识的感官，如同身处它所在空间一样释放该法术。",
    },
    "proficiency-bonus-uses": {
        "source_fragment": "27:pb-uses",
        "source_excerpt": "每天如此施法的次数等于你的熟练加值次；完成一次长休后恢复所有已消耗使用次数。",
    },
    "movement": {
        "source_fragment": "27:movement",
        "source_excerpt": "以附赠动作令灵体意识飘浮到其周围30尺内、你或它可见且未占据的空间；可穿过生物但不能穿过物件。",
    },
    "distance-expiry": {
        "source_fragment": "27:distance-expiry",
        "source_excerpt": "若与你的距离超过300尺，显现将停止。",
    },
    "dispel-magic-expiry": {
        "source_fragment": "27:dispel-expiry",
        "source_excerpt": "若被某人施展了解除魔法 Dispel Magic，显现将停止。",
    },
    "spellbook-destruction-expiry": {
        "source_fragment": "27:source-destruction-expiry",
        "source_excerpt": "若觉醒魔法书被摧毁，显现将停止。",
    },
    "owner-death-expiry": {
        "source_fragment": "27:owner-death-expiry",
        "source_excerpt": "你死亡时，显现将停止。",
    },
    "owner-dismissal-expiry": {
        "source_fragment": "27:owner-dismissal-expiry",
        "source_excerpt": "你可以以一个附赠动作将灵体意识驱散。",
    },
    "long-rest-reactivation": {
        "source_fragment": "27:reactivation",
        "source_excerpt": "显现过灵体意识后，必须完成一次长休或消耗一枚任意环位法术位，才能再次显现。",
    },
}


def choice_input(key: str, options_source: str) -> dict[str, Any]:
    return {
        "key": key,
        "kind": "choice",
        "parameters": {
            "options_source": options_source,
            "duplicate_policy": "forbid",
        },
    }


# The mapping is deliberately explicit.  A few entries are reviewed typed IR
# but marked incomplete because the current consumer catalog has no truthful
# operator for one remaining sentence (teleportation, magic-item creation,
# or a companion profile).  They count as authored/reviewed, never as full.
AUTHORING: dict[str, dict[str, Any]] = {
    # Fathomless / Rune Knight.
    "tashas-cauldron:atom:008f917eace997a6a54939d5:gift-of-the-sea:003": {
        "slug": "fathomless-gift-of-the-sea",
        "clauses": [clause("swim", [effect("grant_movement_mode", mode="swim", speed_ft=40)])],
    },
    "tashas-cauldron:atom:008f917eace997a6a54939d5:oceanic-soul:004": {
        "slug": "fathomless-oceanic-soul",
        "source_completeness": "incomplete",
        "unmodeled": ["underwater mutual language comprehension requires a communication consumer"],
        "clauses": [clause("cold-resistance", [effect("grant_resistance", damage_type="cold", source="oceanic_soul")])],
    },
    "tashas-cauldron:atom:0739d5dfe5855a9afc8f3a53:bonus-proficiencies:001": {
        "slug": "rune-knight-bonus-proficiencies",
        "clauses": [
            clause("smith-tools", [effect("grant_proficiency", proficiency_kind="tool", asset_id="smith_tools", operation="grant", if_already_proficient="replacement_tool_choice")]),
            clause("giant-language", [effect("grant_language", language_id="giant", operation="grant")]),
        ],
    },
    "tashas-cauldron:atom:0739d5dfe5855a9afc8f3a53:giant-s-might:009": {
        "slug": "rune-knight-giants-might",
        "clauses": [
            clause("activate", [effect("consume_resource", resource_key="giants_might_uses", operation="consume", amount=1)], trigger="explicit_activation", activation="automatic", action_economy="bonus_action", duration="one_minute"),
            clause("strength-advantage", [effect("impose_advantage", stat="strength_check_and_save", operation="advantage", scope="self", applies_when="giants_might")], trigger="ability_check", activation="automatic", action_economy="none", duration="one_minute"),
            clause("extra-damage", [effect("add_damage", damage_type="weapon_or_unarmed", formula="1d6", source="giants_might", applies_when="once_per_turn")], trigger="attack_hit", activation="automatic", action_economy="none", duration="one_minute"),
            clause("recovery", [effect("restore_resource", resource_key="giants_might_uses", operation="set_to_max", amount_source="all", recovery_event="long_rest_completed")], trigger="long_rest_completed", duration=None),
        ],
    },
    "tashas-cauldron:atom:0739d5dfe5855a9afc8f3a53:great-stature:011": {
        "slug": "rune-knight-great-stature",
        "clauses": [clause("giants-might-die", [effect("add_damage", damage_type="weapon_or_unarmed", formula="1d8", source="giants_might", applies_when="giants_might")], trigger="attack_hit")],
    },
    "tashas-cauldron:atom:0739d5dfe5855a9afc8f3a53:runic-shield:010": {
        "slug": "rune-knight-runic-shield",
        "clauses": [
            clause("reroll-window", [
                effect("consume_resource", resource_key="runic_shield_uses", operation="consume", amount=1),
                effect("create_reaction_window", window_kind="attack_reroll", expires="current_turn", target_policy={"mode": "ally"}),
            ], trigger="attack_hit", activation="explicit_player_choice", action_economy="reaction", duration="current_turn"),
            clause("recovery", [effect("restore_resource", resource_key="runic_shield_uses", operation="set_to_max", amount_source="all", recovery_event="long_rest_completed")], trigger="long_rest_completed", duration=None),
        ],
    },
    # Battle Master maneuvers not already represented by the existing batch.
    "tashas-cauldron:atom:12139219bf7e575f9cde019c:bait-and-switch:002": {
        "slug": "battle-master-bait-and-switch",
        "clauses": [clause("swap-and-ac", [
            effect("consume_resource", resource_key="superiority_dice", operation="consume", amount=1),
            effect("create_timed_modifier", stat="armor_class", operation="add", value_source="superiority_die", scope="self", applies_when="bait_and_switch", duration="current_turn"),
        ], trigger="explicit_activation", activation="explicit_player_choice", action_economy="none", duration="current_turn")],
    },
    "tashas-cauldron:atom:12139219bf7e575f9cde019c:brace:003": {
        "slug": "battle-master-brace",
        "clauses": [clause("reaction-attack", [
            effect("consume_resource", resource_key="superiority_dice", operation="consume", amount=1),
            effect("create_triggered_attack_window", window_kind="brace_attack", parent_action="weapon_attack", target_policy={"mode": "triggering_enemy"}, expires="current_turn", reaction_type="reaction", attack_profile={"add_damage_formula": "superiority_die"}),
        ], trigger="action_resolved", activation="explicit_player_choice", action_economy="reaction", duration="current_turn")],
    },
    "tashas-cauldron:atom:12139219bf7e575f9cde019c:grappling-strike:005": {
        "slug": "battle-master-grappling-strike",
        "clauses": [
            clause("grapple-cost", [effect("consume_resource", resource_key="superiority_dice", operation="consume", amount=1)], trigger="attack_hit", activation="explicit_player_choice", action_economy="bonus_action", duration="current_turn"),
            clause("grapple-check", [effect("add_modifier", stat="athletics_check", operation="add", value_source="superiority_die", scope="self", applies_when="grappling_strike")], trigger="attack_hit", activation="automatic", action_economy="none", duration="current_turn"),
        ],
    },
    "tashas-cauldron:atom:12139219bf7e575f9cde019c:quick-toss:006": {
        "slug": "battle-master-quick-toss",
        "clauses": [clause("thrown-attack", [
            effect("consume_resource", resource_key="superiority_dice", operation="consume", amount=1),
            effect("create_triggered_attack_window", window_kind="quick_toss_attack", parent_action="bonus_action", target_policy={"mode": "chosen_enemy"}, expires="current_turn", reaction_type="bonus_action", attack_profile={"add_damage_formula": "superiority_die"}),
        ], trigger="action_resolved", activation="automatic", action_economy="bonus_action", duration="current_turn")],
    },
    "tashas-cauldron:atom:12139219bf7e575f9cde019c:tactical-assessment:007": {
        "slug": "battle-master-tactical-assessment",
        "clauses": [clause("check-bonus", [
            effect("consume_resource", resource_key="superiority_dice", operation="consume", amount=1),
            effect("add_modifier", stat="investigation_history_or_insight", operation="add", value_source="superiority_die", scope="self", applies_when="tactical_assessment"),
        ], trigger="ability_check", activation="explicit_player_choice", action_economy="none", duration="current_turn")],
    },
    # Feats: choice inputs are retained as typed bindings rather than guessed.
    "tashas-cauldron:atom:1924837fba5aec4d15a290b8:crusher:003": {
        "slug": "feat-crusher",
        "clauses": [clause("critical-opening", [effect("impose_advantage", stat="attack_roll_against_target", operation="advantage", scope="target", applies_when="bludgeoning_critical")], trigger="attack_hit", activation="automatic", duration="current_turn")],
    },
    "tashas-cauldron:atom:1924837fba5aec4d15a290b8:fey-touched:005": {
        "slug": "feat-fey-touched",
        "clauses": [
            {**clause("misty-step", [effect("grant_spell", spell_id="misty_step", source_class="feat", casting_ability="chosen_ability", grant_mode="free_cast", free_cast_resource_key="fey_touched_misty_step")]), "required_inputs": [choice_input("chosen_ability", "intelligence_wisdom_charisma")]},
            {**clause("chosen-divination-or-enchantment", [effect("grant_spell", spell_id="chosen_divination_or_enchantment_1", source_class="feat", casting_ability="chosen_ability", grant_mode="free_cast", free_cast_resource_key="fey_touched_1st_level_spell")]), "required_inputs": [choice_input("chosen_1st_level_spell", "divination_or_enchantment_1st_level")]},
        ],
    },
    "tashas-cauldron:atom:1924837fba5aec4d15a290b8:shadow-touched:011": {
        "slug": "feat-shadow-touched",
        "clauses": [
            {**clause("invisibility", [effect("grant_spell", spell_id="invisibility", source_class="feat", casting_ability="chosen_ability", grant_mode="free_cast", free_cast_resource_key="shadow_touched_invisibility")]), "required_inputs": [choice_input("chosen_ability", "intelligence_wisdom_charisma")]},
            {**clause("chosen-illusion-or-necromancy", [effect("grant_spell", spell_id="chosen_illusion_or_necromancy_1", source_class="feat", casting_ability="chosen_ability", grant_mode="free_cast", free_cast_resource_key="shadow_touched_1st_level_spell")]), "required_inputs": [choice_input("chosen_1st_level_spell", "illusion_or_necromancy_1st_level")]},
        ],
    },
    "tashas-cauldron:atom:1924837fba5aec4d15a290b8:skill-expert:012": {
        "slug": "feat-skill-expert",
        "clauses": [
            {**clause("skill-proficiency", [effect("grant_proficiency", proficiency_kind="skill", asset_id="chosen_skill", operation="grant")]), "required_inputs": [choice_input("chosen_skill", "skill_list")]},
            {**clause("skill-expertise", [effect("grant_passive_modifier", stat="chosen_skill_check", operation="add", value_source="proficiency_bonus", scope="self", applies_when="chosen_skill_expertise")]), "required_inputs": [choice_input("expertise_skill", "skill_list_only_proficient")]},
        ],
    },
    "tashas-cauldron:atom:1924837fba5aec4d15a290b8:telepathic:015": {
        "slug": "feat-telepathic",
        "clauses": [
            {**clause("telepathy", [effect("expose_authorized_target_information", information_kind="telepathic_communication", range_ft=60, visibility="owner")], trigger="explicit_activation", activation="explicit_player_choice", action_economy="none", duration="advancement_persistent"), "required_inputs": [choice_input("known_language", "known_languages")]},
            {**clause("detect-thoughts", [effect("grant_spell", spell_id="detect_thoughts", source_class="feat", casting_ability="chosen_ability", grant_mode="free_cast", free_cast_resource_key="telepathic_detect_thoughts")]), "required_inputs": [choice_input("chosen_ability", "intelligence_wisdom_charisma")]},
        ],
    },
    # Optional class features and basic class progression contracts.
    "tashas-cauldron:atom:28894d328bca545cc65f7eb9:blind-fighting:004": {
        "slug": "paladin-blind-fighting",
        "clauses": [clause("blindsight", [effect("grant_sight_mode", mode="blindsight", range_ft=10)])],
    },
    "tashas-cauldron:atom:28894d328bca545cc65f7eb9:interception:005": {
        "slug": "paladin-interception",
        "clauses": [clause("damage-interception", [
            effect("create_reaction_window", window_kind="damage_reduction", expires="current_turn", target_policy={"mode": "ally_within_5_feet"}),
        ], trigger="damage_before_apply", activation="explicit_player_choice", action_economy="reaction", duration="current_turn")],
    },
    "tashas-cauldron:atom:28894d328bca545cc65f7eb9:blessed-warrior:003": {
        "slug": "paladin-blessed-warrior",
        "clauses": [
            {**clause("cantrip-one", [effect("grant_spell", spell_id="chosen_cleric_cantrip_1", source_class="cleric", casting_ability="charisma", grant_mode="known")]), "required_inputs": [choice_input("cantrip_1", "cleric_cantrips")]},
            {**clause("cantrip-two", [effect("grant_spell", spell_id="chosen_cleric_cantrip_2", source_class="cleric", casting_ability="charisma", grant_mode="known")]), "required_inputs": [choice_input("cantrip_2", "cleric_cantrips")]},
        ],
    },
    "tashas-cauldron:atom:28894d328bca545cc65f7eb9:harness-divine-power:006": {
        "slug": "paladin-harness-divine-power",
        "clauses": [clause("spell-slot-exchange", [effect("exchange_resource", from_resource_key="channel_divinity", to_resource_key="spell_slot", operation="exchange", amount_source="half_proficiency_bonus_rounded_up")], trigger="explicit_activation", activation="automatic", action_economy="bonus_action", duration="current_turn")],
    },
    "tashas-cauldron:atom:2ceef8846dfb30c175abe0dd:tool-expertise:007": {
        "slug": "artificer-tool-expertise",
        "clauses": [clause("double-proficiency", [effect("grant_passive_modifier", stat="tool_check", operation="add", value_source="proficiency_bonus", scope="self", applies_when="proficient_tool")])],
    },
    "tashas-cauldron:atom:38a389e4b25a6eeec6c7835f:bonus-proficiencies:002": {
        "slug": "order-cleric-bonus-proficiencies",
        "clauses": [
            clause("heavy-armor", [effect("grant_proficiency", proficiency_kind="armor", asset_id="heavy_armor", operation="grant")]),
            {**clause("social-skill", [effect("grant_proficiency", proficiency_kind="skill", asset_id="intimidation_or_persuasion", operation="grant")]), "required_inputs": [choice_input("social_skill", "intimidation_persuasion")]},
        ],
    },
    "tashas-cauldron:atom:4041ef4e8e0a5b7375019c27:training-in-sword-and-song:001": {
        "slug": "bladesinger-training-in-sword-and-song",
        "clauses": [clause("weapon-proficiency", [effect("grant_proficiency", proficiency_kind="weapon", asset_id="one_handed_melee_weapon", operation="grant")])],
    },
    "tashas-cauldron:atom:63d0abe27f6ad161f0820593:bonus-proficiencies:002": {
        "slug": "twilight-cleric-bonus-proficiencies",
        "clauses": [
            clause("martial-weapons", [effect("grant_proficiency", proficiency_kind="weapon", asset_id="martial_weapons", operation="grant")]),
            clause("heavy-armor", [effect("grant_proficiency", proficiency_kind="armor", asset_id="heavy_armor", operation="grant")]),
        ],
    },
    "tashas-cauldron:atom:63d0abe27f6ad161f0820593:eyes-of-night:003": {
        "slug": "twilight-cleric-eyes-of-night",
        "clauses": [
            clause("darkvision", [effect("grant_sight_mode", mode="darkvision", range_source="twilight_domain_darkvision")]),
            clause("share-darkvision", [effect("expose_authorized_target_information", information_kind="shared_darkvision", range_ft=300, visibility="owner")], trigger="explicit_activation", activation="explicit_player_choice", action_economy="none", duration="one_hour"),
        ],
    },
    "tashas-cauldron:atom:63d0abe27f6ad161f0820593:steps-of-night:006": {
        "slug": "twilight-cleric-steps-of-night",
        "clauses": [clause("fly", [effect("grant_movement_mode", mode="fly", speed_source="walking_speed", applies_when="dim_light_or_darkness")], trigger="explicit_activation", activation="automatic", action_economy="bonus_action", duration="one_minute")],
    },
    "tashas-cauldron:atom:6ac3dd8adf2acd63eeabf4ea:otherworldly-glamour:003": {
        "slug": "fey-wanderer-otherworldly-glamour",
        "clauses": [
            {**clause("skill-proficiency", [effect("grant_proficiency", proficiency_kind="skill", asset_id="chosen_social_skill", operation="grant")]), "required_inputs": [choice_input("chosen_social_skill", "deception_performance_persuasion") ]},
            clause("wisdom-check-bonus", [effect("grant_passive_modifier", stat="charisma_check", operation="add", value_source="wisdom_modifier", scope="self", applies_when="social_check")]),
        ],
    },
    # Fighting styles / Ranger optional features.
    "tashas-cauldron:atom:752d57e35706db428895da0a:blind-fighting:008": {
        "slug": "ranger-blind-fighting",
        "clauses": [clause("blindsight", [effect("grant_sight_mode", mode="blindsight", range_ft=10)])],
    },
    "tashas-cauldron:atom:752d57e35706db428895da0a:canny-1:002": {
        "slug": "ranger-canny",
        "clauses": [
            {**clause("skill-proficiency", [effect("grant_proficiency", proficiency_kind="skill", asset_id="chosen_skill", operation="grant")]), "required_inputs": [choice_input("chosen_skill", "ranger_skill_list")]},
            {**clause("skill-expertise", [effect("grant_passive_modifier", stat="chosen_skill_check", operation="add", value_source="proficiency_bonus", scope="self", applies_when="chosen_skill_expertise")]), "required_inputs": [choice_input("expertise_skill", "chosen_skill")]},
            {**clause("language", [effect("grant_language", language_id="chosen_language", operation="grant")]), "required_inputs": [choice_input("chosen_language", "languages")]},
        ],
    },
    "tashas-cauldron:atom:752d57e35706db428895da0a:druidic-warrior:009": {
        "slug": "ranger-druidic-warrior",
        "clauses": [
            {**clause("cantrip-one", [effect("grant_spell", spell_id="chosen_druid_cantrip_1", source_class="druid", casting_ability="wisdom", grant_mode="known")]), "required_inputs": [choice_input("cantrip_1", "druid_cantrips")]},
            {**clause("cantrip-two", [effect("grant_spell", spell_id="chosen_druid_cantrip_2", source_class="druid", casting_ability="wisdom", grant_mode="known")]), "required_inputs": [choice_input("cantrip_2", "druid_cantrips")]},
        ],
    },
    "tashas-cauldron:atom:752d57e35706db428895da0a:roving-6:003": {
        "slug": "ranger-roving",
        "clauses": [
            clause("walk-speed", [effect("grant_passive_modifier", stat="speed_ft", operation="add", value=5, scope="self", applies_when="not_wearing_heavy_armor")]),
            clause("swim-speed", [effect("grant_movement_mode", mode="swim", speed_source="walking_speed", requires_not_wearing_heavy_armor=True)]),
            clause("climb-speed", [effect("grant_movement_mode", mode="climb", speed_source="walking_speed", requires_not_wearing_heavy_armor=True)]),
        ],
    },
    "tashas-cauldron:atom:752d57e35706db428895da0a:tireless-10:004": {
        "slug": "ranger-tireless",
        "source_completeness": "complete",
        "clauses": [clause("remove-exhaustion", [effect("remove_condition", condition="exhaustion")], trigger="short_rest_completed", activation="automatic", action_economy="none", duration=None)],
    },
    "tashas-cauldron:atom:790ce45021cc1901403353e1:implement-of-peace:002": {
        "slug": "peace-cleric-implement-of-peace",
        "clauses": [
            clause("insight", [effect("grant_proficiency", proficiency_kind="skill", asset_id="insight", operation="grant")]),
            clause("medicine", [effect("grant_proficiency", proficiency_kind="skill", asset_id="medicine", operation="grant")]),
            clause("persuasion", [effect("grant_proficiency", proficiency_kind="skill", asset_id="persuasion", operation="grant")]),
        ],
    },
    "tashas-cauldron:atom:867896faa26eb295d846a574:glorious-defense:010": {
        "slug": "glory-paladin-glorious-defense",
        "clauses": [clause("defense-window", [
            effect("consume_resource", resource_key="glorious_defense_uses", operation="consume", amount=1),
            effect("create_timed_modifier", stat="armor_class", operation="add", value_source="charisma_modifier", scope="target", applies_when="glorious_defense", duration="current_turn"),
            effect("create_triggered_attack_window", window_kind="glorious_defense_counterattack", parent_action="reaction", target_policy={"mode": "attacker_within_reach"}, expires="current_turn", reaction_type="reaction"),
        ], trigger="attack_hit", activation="explicit_player_choice", action_economy="reaction", duration="current_turn")],
    },
    # Genie / Psi / Beast / Astral.
    "tashas-cauldron:atom:98620543cf94e974361c6567:bottled-respit:003": {
        "slug": "genie-bottled-respite",
        "source_completeness": "incomplete",
        "unmodeled": [
            "formal vessel persistence and entity containment consumer",
            "source-bound exit placement and item relocation receipts",
            "sanctuary-vessel companion selection and short-rest benefit consumer",
        ],
        "clauses": [
            clause(
                "vessel-space-contract",
                [
                    effect(
                        "configure_vessel_space",
                        vessel_binding="feature_source",
                        max_occupants=1,
                        duration_hours_source="proficiency_bonus_times_2",
                        exit_size_cells=1,
                        appearance_options=[
                            "oil_lamp",
                            "urn",
                            "ring",
                            "stoppered_bottle",
                            "hollow_figurine",
                            "lantern",
                        ],
                    )
                ],
                trigger="explicit_activation",
                activation="automatic",
                action_economy="action",
                duration="until_long_rest",
            )
        ],
    },
    "tashas-cauldron:atom:98620543cf94e974361c6567:elemental-gift:005": {
        "slug": "genie-elemental-gift",
        "clauses": [
            {**clause("resistance", [effect("grant_resistance", damage_type="chosen_genie_element", source="elemental_gift")]), "required_inputs": [choice_input("element", "genie_element_types")]},
            {**clause("flight", [effect("grant_movement_mode", mode="fly", speed_source="walking_speed", applies_when="elemental_gift")]), "required_inputs": [choice_input("element", "genie_element_types")]},
        ],
    },
    "tashas-cauldron:atom:98620543cf94e974361c6567:genie-s-wrath:004": {
        "slug": "genie-genies-wrath",
        "clauses": [
            {**clause("extra-damage", [effect("add_damage", damage_type="chosen_genie_damage_type", formula="proficiency_bonus", source="genies_wrath", applies_when="once_per_turn")], trigger="attack_hit"), "required_inputs": [choice_input("damage_type", "genie_damage_type")]},
        ],
    },
    "tashas-cauldron:atom:a13253dc90904c96eaa719ab:guarded-mind:008": {
        "slug": "psi-warrior-guarded-mind",
        "clauses": [
            clause("psychic-resistance", [effect("grant_resistance", damage_type="psychic", source="guarded_mind")]),
            clause("condition-break", [effect("remove_condition", condition="charmed_or_frightened")], trigger="explicit_activation", activation="explicit_player_choice", action_economy="none", duration="current_turn"),
        ],
    },
    "tashas-cauldron:atom:a13253dc90904c96eaa719ab:psi-powered-leap:006": {
        "slug": "psi-warrior-psi-powered-leap",
        "clauses": [clause("flight", [
            effect("consume_resource", resource_key="psionic_dice", operation="consume", amount=1),
            effect("grant_movement_mode", mode="fly", speed_source="walking_speed", applies_when="psi_powered_leap"),
        ], trigger="explicit_activation", activation="automatic", action_economy="bonus_action", duration="current_turn")],
    },
    "tashas-cauldron:atom:a13253dc90904c96eaa719ab:psionic:001": {
        "slug": "psi-warrior-psionic-power",
        "clauses": [clause("dice-pool", [effect("set_resource_profile", resource_key="psionic_dice", resource_kind="psionic_dice", die_size=6, max_formula="2 * proficiency_bonus", recovery_events=[{"rest": "short_rest", "operation": "set_to_max"}, {"rest": "long_rest", "operation": "set_to_max"}])])],
    },
    "tashas-cauldron:atom:a13253dc90904c96eaa719ab:telekinetic-master:010": {
        "slug": "psi-warrior-telekinetic-master",
        "clauses": [
            clause("telekinesis", [effect("grant_spell", spell_id="telekinesis", source_class="fighter", casting_ability="intelligence", grant_mode="free_cast", free_cast_resource_key="telekinetic_master")]),
            clause("recovery", [effect("restore_resource", resource_key="telekinetic_master", operation="set_to_max", amount_source="all", recovery_event="long_rest_completed")], trigger="long_rest_completed", duration=None),
        ],
    },
    "tashas-cauldron:atom:b23e97de6529e42be59f8b0d:bestial-soul:005": {
        "slug": "beast-barbarian-bestial-soul",
        "clauses": [
            {**clause("swim", [effect("grant_movement_mode", mode="swim", speed_source="walking_speed", selection_binding={"choice_key": "bestial_soul_mode"})]), "required_inputs": [choice_input("bestial_soul_mode", "swim_climb_jump")]},
            {**clause("climb", [effect("grant_movement_mode", mode="climb", speed_source="walking_speed", selection_binding={"choice_key": "bestial_soul_mode"})]), "required_inputs": [choice_input("bestial_soul_mode", "swim_climb_jump")]},
        ],
    },
    "tashas-cauldron:atom:b6d0bbfbdc36f195e62683c5:armor-of-the-spirit:010": {
        "slug": "astral-self-armor-of-the-spirit",
        "clauses": [clause("astral-ac", [effect("set_modifier", stat="armor_class", operation="set_base", value_source="wisdom_modifier", scope="self", applies_when="astral_arms_active")])],
    },
    "tashas-cauldron:atom:b6d0bbfbdc36f195e62683c5:astral-sight:003": {
        "slug": "astral-self-astral-sight",
        "clauses": [
            clause("darkvision", [effect("grant_sight_mode", mode="darkvision", range_ft=120, applies_when="astral_form_active")]),
            clause("see-invisible", [effect("grant_sight_mode", mode="truesight", range_ft=120, applies_when="astral_form_active")]),
        ],
    },
    "tashas-cauldron:atom:b6d0bbfbdc36f195e62683c5:word-of-the-spirit:005": {
        "slug": "astral-self-word-of-the-spirit",
        "clauses": [clause("telepathic-speech", [effect("expose_authorized_target_information", information_kind="telepathic_speech", range_ft=60, visibility="owner")], trigger="explicit_activation", activation="explicit_player_choice", action_economy="none", duration="ten_minutes")],
    },
    "tashas-cauldron:atom:b79182b9e28e7cac95e7c7a5:full-of-stars:010": {
        "slug": "stars-druid-full-of-stars",
        "clauses": [
            clause("damage-resistance", [effect("grant_resistance", damage_type="bludgeoning_piercing_slashing", source="starry_form")], trigger="explicit_activation", activation="automatic", action_economy="none", duration="ten_minutes"),
            clause("concentration", [effect("grant_saving_throw_advantage", applies_when="starry_form_concentration")], trigger="explicit_activation", activation="automatic", action_economy="none", duration="ten_minutes"),
        ],
    },
    "tashas-cauldron:atom:b79182b9e28e7cac95e7c7a5:weal:007": {
        "slug": "stars-druid-weal",
        "clauses": [clause("ally-roll", [effect("add_modifier", stat="ally_d20_roll", operation="add", value_source="starry_dice", scope="target", applies_when="within_30_feet")], trigger="ability_check", activation="explicit_player_choice", action_economy="none", targeting={"kind": "ally", "parameters": {}}, duration="current_turn")],
    },
    "tashas-cauldron:atom:b79182b9e28e7cac95e7c7a5:woe:008": {
        "slug": "stars-druid-woe",
        "clauses": [clause("enemy-roll", [effect("add_modifier", stat="enemy_d20_roll", operation="subtract", value_source="starry_dice", scope="target", applies_when="within_30_feet")], trigger="ability_check", activation="explicit_player_choice", action_economy="none", duration="current_turn")],
    },
    # Soulknife and the remaining high-value feature seams.
    "tashas-cauldron:atom:b63c217774b977cdb0c1a23e:homing-strikes:006": {
        "slug": "soulknife-homing-strikes",
        "clauses": [clause("miss-correction", [
            effect("consume_resource", resource_key="psionic_dice", operation="consume", amount=1),
            effect("add_modifier", stat="attack_roll", operation="add", value_source="psionic_die", scope="self", applies_when="attack_missed"),
        ], trigger="attack_missed", activation="explicit_player_choice", action_economy="none", duration="current_turn")],
    },
    "tashas-cauldron:atom:b63c217774b977cdb0c1a23e:psi-bolstered-knack:002": {
        "slug": "soulknife-psi-bolstered-knack",
        "clauses": [clause("check-correction", [
            effect("consume_resource", resource_key="psionic_dice", operation="consume", amount=1),
            effect("add_modifier", stat="failed_skill_check", operation="add", value_source="psionic_die", scope="self", applies_when="skill_check"),
        ], trigger="ability_check", activation="explicit_player_choice", action_economy="none", duration="current_turn")],
    },
    "tashas-cauldron:atom:b63c217774b977cdb0c1a23e:psychic-teleportation:007": {
        "slug": "soulknife-psychic-teleportation",
        "source_completeness": "incomplete",
        "unmodeled": ["teleport destination resolution has no current movement consumer"],
        "clauses": [clause("teleport-window", [effect("consume_resource", resource_key="psionic_dice", operation="consume", amount=1)], trigger="explicit_activation", activation="automatic", action_economy="bonus_action", duration="current_turn")],
    },
    "tashas-cauldron:atom:b63c217774b977cdb0c1a23e:psychic-whispers:003": {
        "slug": "soulknife-psychic-whispers",
        "clauses": [clause("telepathic-link", [effect("expose_authorized_target_information", information_kind="telepathic_link", range_ft=60, visibility="owner")], trigger="explicit_activation", activation="automatic", action_economy="action", duration="one_hour")],
    },
    "tashas-cauldron:atom:cf864e58ba0d62c93110f5c6:powered-steps:010": {
        "slug": "armorer-powered-steps",
        "clauses": [clause("speed", [effect("grant_passive_modifier", stat="speed_ft", operation="add", value=5, scope="self", applies_when="wearing_power_armor")])],
    },
    "tashas-cauldron:atom:dc4f2bf18baca6ec97d7d0bf:alchemical-savant:004": {
        "slug": "alchemist-alchemical-savant",
        "clauses": [
            clause("acid-fire-necrotic-poison", [effect("spell_damage_modifier", operation="add", formula="intelligence_modifier", ability="intelligence", applies_when="acid_fire_necrotic_or_poison_damage")]),
            clause("healing", [effect("spell_healing_modifier", operation="add", formula="intelligence_modifier", ability="intelligence", applies_when="healing_roll")]),
        ],
    },
    "tashas-cauldron:atom:dc4f2bf18baca6ec97d7d0bf:alchemist-spells:002": {
        "slug": "alchemist-spell-list",
        "clauses": [clause("always-prepared", [
            effect("grant_spell", spell_id="healing_word", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="ray_of_sickness", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="flaming_sphere", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="melfs_acid_arrow", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="gaseous_form", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="mass_healing_word", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="blight", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="death_ward", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="cloudkill", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
            effect("grant_spell", spell_id="raise_dead", source_class="artificer", casting_ability="intelligence", grant_mode="always_prepared"),
        ])],
    },
    "tashas-cauldron:atom:e94f0c903dd025796d7a2d22:psionic-sorcery:003": {
        "slug": "aberrant-mind-psionic-sorcery",
        "clauses": [
            clause("component-override", [effect("override_spell_components", component="verbal_somatic_material_without_cost", operation="ignore", applies_when="psionic_spell")]),
            clause("payment-override", [effect("override_spell_payment", payment_kind="spell_slot", operation="replace_with_sorcery_points", resource_key="sorcery_points", applies_when="psionic_spell")]),
        ],
    },
    "tashas-cauldron:atom:e94f0c903dd025796d7a2d22:psionic-spells:001": {
        "slug": "aberrant-mind-psionic-spell-list",
        "clauses": [clause("known-spells", [
            effect("grant_spell", spell_id="arms_of_hadar", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="dissonant_whispers", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="mind_spike", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="calm_emotions", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="detect_thoughts", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="hunger_of_hadar", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="sending", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="evards_black_tentacles", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="summon_aberration", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="telekinesis", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
        ])],
    },
    "tashas-cauldron:atom:e94f0c903dd025796d7a2d22:telepathic-speech:002": {
        "slug": "aberrant-mind-telepathic-speech",
        "clauses": [clause("telepathic-link", [effect("expose_authorized_target_information", information_kind="telepathic_link", range_ft=30, visibility="owner")], trigger="explicit_activation", activation="automatic", action_economy="bonus_action", duration="one_minute")],
    },
    "tashas-cauldron:atom:ee901996f0fcc3e576657e06:clockwork-magic:001": {
        "slug": "clockwork-soul-clockwork-magic",
        "clauses": [clause("known-spells", [
            effect("grant_spell", spell_id="alarm", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="protection_from_good_and_evil", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="aid", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="lesser_restoration", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="dispel_magic", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="counterspell", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="freedom_of_movement", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="summon_construct", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="greater_restoration", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
            effect("grant_spell", spell_id="wall_of_force", source_class="sorcerer", casting_ability="charisma", grant_mode="known"),
        ])],
    },
    "tashas-cauldron:atom:f8e42149abd618bfa3d0eac1:writhing-tide:003": {
        "slug": "swarmkeeper-writhing-tide",
        "clauses": [clause("flight", [effect("grant_movement_mode", mode="fly", speed_source="fixed_10_feet", applies_when="swarmkeeper")], trigger="explicit_activation", activation="automatic", action_economy="bonus_action", duration="one_minute")],
    },
    "tashas-cauldron:atom:f8e42149abd618bfa3d0eac1:swarmkeeper-magic:002": {
        "slug": "swarmkeeper-spell-list",
        "clauses": [clause("known-spells", [
            effect("grant_spell", spell_id="mage_hand", source_class="ranger", casting_ability="wisdom", grant_mode="known"),
            effect("grant_spell", spell_id="faerie_fire", source_class="ranger", casting_ability="wisdom", grant_mode="known"),
            effect("grant_spell", spell_id="web", source_class="ranger", casting_ability="wisdom", grant_mode="known"),
            effect("grant_spell", spell_id="gaseous_form", source_class="ranger", casting_ability="wisdom", grant_mode="known"),
            effect("grant_spell", spell_id="arcane_eye", source_class="ranger", casting_ability="wisdom", grant_mode="known"),
            effect("grant_spell", spell_id="insect_plague", source_class="ranger", casting_ability="wisdom", grant_mode="known"),
        ])],
    },
    "tashas-cauldron:atom:fbf8451f879a169fb17a01e9:arcane-firearm:004": {
        "slug": "artillerist-arcane-firearm",
        "clauses": [clause("spell-damage", [effect("spell_damage_modifier", operation="add", formula="1d8", applies_when="spell_cast_through_arcane_firearm")])],
    },
    "tashas-cauldron:atom:fbf8451f879a169fb17a01e9:explosive-cannon:005": {
        "slug": "artillerist-explosive-cannon",
        "clauses": [
            clause("cannon-damage", [effect("add_damage", damage_type="force", formula="1d8", source="eldritch_cannon", applies_when="eldritch_cannon")], trigger="attack_hit"),
            clause("detonate", [effect("activate_condition", condition="eldritch_cannon_detonation", duration="current_turn")], trigger="explicit_activation", activation="automatic", action_economy="action", duration="current_turn"),
        ],
    },
    "tashas-cauldron:atom:ff7049c6a4d0aad0dae4adf5:manifest-mind:002": {
        "slug": "scribe-manifest-mind",
        "source_completeness": "complete",
        "unmodeled": [],
        "clauses": [
            clause("activation-source-and-initial-placement", [effect(
                "configure_entity_lifecycle",
                entity_type="spectral_object",
                source_binding="feature_source",
                max_entries=1,
                initial_placement={
                    "source_object_held": True,
                    "max_distance_ft": 60,
                    "destination_unoccupied": True,
                },
            )], trigger="advancement_confirmed", action_economy="none", duration="advancement_persistent"),
            clause("spectral-object-form", [effect(
                "configure_entity_senses",
                entity_binding="entity_lifecycle",
                form={
                    "intangible": True,
                    "occupies_space": False,
                    "appearance": ["spectral dossier", "stack of writing", "historical scholar"],
                },
                senses={"light_radius_ft": 10},
            )], trigger="explicit_activation", action_economy="bonus_action", duration="advancement_persistent"),
            clause("entity-senses", [effect(
                "configure_entity_senses",
                entity_binding="entity_lifecycle",
                senses={"hearing": True, "darkvision_ft": 60},
            )], trigger="explicit_activation", action_economy="bonus_action", duration="advancement_persistent"),
            clause("telepathic-sharing", [effect(
                "share_authorized_sensory_information",
                entity_binding="entity_lifecycle",
                information_kind="authorized_entity_senses",
                language_required=False,
                response_required=False,
                visibility="owner",
                range_ft=300,
            )], trigger="explicit_activation", action_economy="none", duration="advancement_persistent"),
            clause("remote-spell-origin", [effect(
                "configure_remote_spell_origin",
                origin_binding="entity_lifecycle",
                origin_kind="entity",
                target_kind="one_creature",
                require_line_of_effect=True,
            )], trigger="spell_cast", action_economy="none", targeting={"kind": "one_creature", "parameters": {}}, duration="current_turn"),
            clause("proficiency-bonus-uses", [effect(
                "set_resource_profile",
                resource_key="entity_sensory_spell_uses",
                resource_kind="uses",
                die_size=2,
                max_formula="proficiency_bonus",
                recovery_events=[{"rest": "long_rest", "operation": "set_to_max"}],
            )], trigger="advancement_confirmed", action_economy="none", duration="advancement_persistent"),
            clause("movement", [effect(
                "configure_entity_spatial",
                entity_binding="entity_lifecycle",
                max_move_ft=30,
                requires_owner_visibility=True,
                requires_unoccupied_destination=True,
                cannot_cross_objects=True,
                cell_size_ft=5,
                expiry_distance_ft=300,
            )], trigger="explicit_activation", action_economy="bonus_action", duration="advancement_persistent"),
            clause("distance-expiry", [effect(
                "configure_entity_spatial",
                entity_binding="entity_lifecycle",
                max_move_ft=30,
                expiry_distance_ft=300,
            )], trigger="explicit_activation", action_economy="none", duration="advancement_persistent"),
            clause("dispel-magic-expiry", [effect(
                "configure_entity_lifecycle",
                entity_type="spectral_object",
                source_binding="feature_source",
                termination_reasons=["dispel_magic"],
            )], trigger="advancement_confirmed", action_economy="none", duration="advancement_persistent"),
            clause("spellbook-destruction-expiry", [effect(
                "configure_entity_lifecycle",
                entity_type="spectral_object",
                source_binding="feature_source",
                termination_reasons=["source_object_destroyed"],
            )], trigger="advancement_confirmed", action_economy="none", duration="advancement_persistent"),
            clause("owner-death-expiry", [effect(
                "configure_entity_lifecycle",
                entity_type="spectral_object",
                source_binding="feature_source",
                expires_on_owner_death=True,
                termination_reasons=["owner_died"],
            )], trigger="advancement_confirmed", action_economy="none", duration="advancement_persistent"),
            clause("owner-dismissal-expiry", [effect(
                "configure_entity_lifecycle",
                entity_type="spectral_object",
                source_binding="feature_source",
                termination_reasons=["owner_dismissed"],
            )], trigger="advancement_confirmed", action_economy="none", duration="advancement_persistent"),
            clause("long-rest-reactivation", [effect(
                "configure_spell_slot_reactivation",
                entity_binding="entity_lifecycle",
                activation_limit=1,
                spell_slot_resource_prefix="spell_slots_",
            )], trigger="explicit_activation", action_economy="none", duration="advancement_persistent"),
        ],
    },
}


def _slug(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-").lower()
    return value or "feature"


def _build_spec(atom: dict[str, Any], mapping: dict[str, Any], record: dict[str, Any]) -> FeatureSpec:
    source_excerpt = _source_body(record, atom).strip()
    source_name = str(atom.get("localized_name") or atom.get("name") or "").strip()
    slug = str(mapping["slug"])
    feature_id = f"content.{PACK_ID}.round2.feature.{slug}"
    clauses = []
    for raw_clause in mapping["clauses"]:
        current = dict(raw_clause)
        boundary = (
            MANIFEST_MIND_BOUNDARIES.get(str(current["clause_id"]))
            if slug == "scribe-manifest-mind"
            else None
        )
        current["audit"] = {
            **dict(current.get("audit") or {}),
            "reviewed_by": REVIEWER,
            "source": "authored_ir",
            "source_excerpt": (boundary or {}).get("source_excerpt", source_excerpt[:4000]),
            "source_fragment": (boundary or {}).get("source_fragment", atom["source_fragment"]),
        }
        clauses.append(current)
    value = {
        "schema_version": "feature-ir-1",
        "feature_id": feature_id,
        "namespace": "content.tashas-cauldron",
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "ruleset_version": RULESET_VERSION,
        "source_record_id": str(atom["source_record_id"]),
        "source_name": source_name,
        "source_trust": "authored_ir",
        "localized_names": {"zh-CN": source_name},
        "class_name": atom.get("class_name"),
        "subclass_name": atom.get("subclass_name"),
        "level": atom.get("level"),
        "source_completeness": mapping.get("source_completeness", "complete"),
        "clauses": clauses,
        "dependencies": [],
        "compatibility": {"runtime_source": "feature_ir", "source_fingerprint": atom["source_fingerprint"]},
        "source_path": atom["source_path"],
        "source_book": SOURCE_BOOK,
        "source_fingerprint": atom["source_fingerprint"],
        "review_status": "reviewed",
        "reviewed_by": REVIEWER,
        "reviewed_fields": [
            "feature_id", "source_record_id", "source_name", "source_path", "source_book",
            "source_fingerprint", "content_kind", "class_name", "subclass_name", "level",
            "source_completeness", "clauses", "required_inputs", "runtime_boundary",
        ],
        "source_evidence": {
            "source_path": atom["source_path"],
            "source_record_id": atom["source_record_id"],
            "source_fragment": atom["source_fragment"],
            "source_excerpt": source_excerpt,
            "clause_boundaries": (
                MANIFEST_MIND_BOUNDARIES if slug == "scribe-manifest-mind" else {}
            ),
        },
        "clause_boundaries": {
            item["clause_id"]: {
                "source_fragment": (
                    MANIFEST_MIND_BOUNDARIES.get(item["clause_id"], {})
                    .get("source_fragment", atom["source_fragment"])
                    if slug == "scribe-manifest-mind"
                    else atom["source_fragment"]
                ),
                "source_excerpt": (
                    MANIFEST_MIND_BOUNDARIES.get(item["clause_id"], {})
                    .get("source_excerpt", source_excerpt[:4000])
                    if slug == "scribe-manifest-mind"
                    else source_excerpt[:4000]
                ),
            }
            for item in clauses
        },
        "manual_decisions": {
            "operator_mapping": "explicit_atom_mapping",
            "unmodeled_source_terms": mapping.get("unmodeled", []),
            "isolated_runtime_only": True,
        },
        "evidence": [f"{source_name}: {source_excerpt[:1200]}"],
        "compiler_fingerprint": COMPILER_FINGERPRINT,
    }
    return FeatureSpec.from_dict(value, path=feature_id)


def main() -> int:
    records = select_source_records(load_records(ROOT / "data/generated-content/dnd5e_chm/json"))
    by_record = {str(item.get("stable_id")): item for item in records}
    migration = build_migration(ROOT)
    atoms = {str(item["atom_id"]): item for item in migration["atoms"]}
    current_typed = migration["typed_entries"]
    missing = sorted(set(AUTHORING) - set(atoms))
    if missing:
        raise SystemExit("unknown atom ids:\n" + "\n".join(missing))
    collisions: list[str] = []
    specs: list[FeatureSpec] = []
    compiler = FeatureCompiler(status_authority="compiler")
    rows: list[dict[str, Any]] = []
    for atom_id, mapping in AUTHORING.items():
        atom = atoms[atom_id]
        existing_matches = _matches_typed(atom, current_typed)
        if existing_matches and not any(
            str(item.get("content_id") or "").startswith("content.tashas-cauldron.round2.feature.")
            for item in existing_matches
        ):
            collisions.append(f"{atom_id}: already has authored provenance")
            continue
        record = by_record[str(atom["source_record_id"])]
        spec = _build_spec(atom, mapping, record)
        compiled = compiler.compile(spec)
        specs.append(spec)
        path = OUTPUT_ROOT / "features" / f"{_slug(mapping['slug'])}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        asset = spec.to_dict()
        # ``kind`` is the workbench envelope discriminator; it is intentionally
        # outside FeatureSpec._FIELDS and is therefore added only after the IR
        # has been parsed and compiled.
        asset["kind"] = "feature"
        path.write_text(json.dumps(asset, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rows.append({
            "atom_id": atom_id,
            "feature_id": spec.feature_id,
            "source_name": spec.source_name,
            "source_record_id": spec.source_record_id,
            "source_fingerprint": spec.source_fingerprint,
            "typed_ir_path": str(path.relative_to(ROOT)),
            "source_completeness": spec.source_completeness,
            "compile": compiled.to_dict(),
            "unmodeled_source_terms": mapping.get("unmodeled", []),
        })
    if collisions:
        raise SystemExit("typed provenance collisions:\n" + "\n".join(collisions))
    if len(rows) != len(AUTHORING):
        raise SystemExit(f"expected {len(AUTHORING)} authored rows, wrote {len(rows)}")
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["compile"]["compile_status"])
        counts[status] = counts.get(status, 0) + 1
    report = {
        "schema_version": "tashas-feature-contract-batch-I-1",
        "pack_id": PACK_ID,
        "source_book": SOURCE_BOOK,
        "reviewed_by": REVIEWER,
        "isolated_runtime_only": True,
        "formal_apply": False,
        "authored_typed_ir": len(rows),
        "compile_status_counts": dict(sorted(counts.items())),
        "compile_full": counts.get("full", 0),
        "reviewed_total": len(rows),
        "manual_boundary_total": sum(bool(row["unmodeled_source_terms"]) for row in rows),
        "entries": sorted(rows, key=lambda item: item["feature_id"]),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"authored_typed_ir": len(rows), "compile_status_counts": counts, "report": str(REPORT_PATH)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
