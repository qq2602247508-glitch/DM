"""Authored Feature IR for the production-harvest and expansion-pack cohort."""

from __future__ import annotations

from typing import Any

from dnd_dm_assistant.domain.feature_ir import FeatureSpec

PACK_ID = "2024-core-harvest-viii"
PACK_VERSION = "1.0.0"
RULESET_VERSION = "2024"


def _clause(
    clause_id: str,
    *,
    effects: list[dict[str, Any]],
    trigger: str = "advancement_confirmed",
    conditions: list[dict[str, Any]] | None = None,
    activation: str = "automatic",
    action_economy: str = "none",
    targeting: dict[str, Any] | None = None,
    duration: object = "advancement_persistent",
    required_inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "clause_id": clause_id,
        "trigger": trigger,
        "conditions": conditions or [],
        "activation": activation,
        "action_economy": action_economy,
        "resource_costs": [],
        "resource_recovery": [],
        "required_inputs": required_inputs or [],
        "targeting": targeting or {"kind": "self", "parameters": {}},
        "effects": effects,
        "duration": duration,
        "expiry": None,
        "stacking": "replace_same_source",
        "frequency": None,
        "persistence": "character.feature_runtime",
        "visibility": "owner",
        "audit": {"source": "authored_ir", "batch": "harvest-viii"},
    }


def _feature(
    feature_id: str,
    *,
    source_name: str,
    class_name: str,
    subclass_name: str,
    level: int,
    source_record_id: str,
    source_excerpt_sha256: str,
    clauses: list[dict[str, Any]],
) -> FeatureSpec:
    return FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": feature_id,
            "namespace": "dnd.2024.core.harvest",
            "pack_id": PACK_ID,
            "pack_version": PACK_VERSION,
            "ruleset_version": RULESET_VERSION,
            "source_record_id": source_record_id,
            "source_name": source_name,
            "source_trust": "authored_ir",
            "localized_names": {"zh-CN": source_name},
            "class_name": class_name,
            "subclass_name": subclass_name,
            "level": level,
            "source_completeness": "complete",
            "clauses": clauses,
            "dependencies": [],
            "compatibility": {
                "runtime_source": "feature_ir",
                "portable_pack_contract": True,
                "source_excerpt_sha256": source_excerpt_sha256,
            },
        },
        path=f"harvest_feature:{feature_id}",
    )


def harvest_feature_specs() -> tuple[FeatureSpec, ...]:
    """Return the eight source-reviewed production-harvest FeatureSpecs."""

    return (
        _feature(
            "dnd2024.subclass.rogue.arcane-trickster.magical-ambush",
            source_name="诡术伏击",
            class_name="游荡者",
            subclass_name="诡术师",
            level=9,
            source_record_id="9cf06e62650334b555019eaf",
            source_excerpt_sha256=(
                "f09ac7c2494a7b18c410cac3685d3dda99e05dd7bcf5a9cb654ef42317230c2e"
            ),
            clauses=[
                _clause(
                    "invisible-spell-save-disadvantage",
                    trigger="spell_cast",
                    conditions=[
                        {
                            "kind": "actor_has_state",
                            "parameters": {"state": "invisible"},
                        }
                    ],
                    targeting={"kind": "enemy", "parameters": {}},
                    duration="current_turn",
                    effects=[
                        {
                            "operator": "impose_disadvantage",
                            "parameters": {
                                "stat": "saving_throw",
                                "operation": "disadvantage",
                                "scope": "target",
                                "applies_when": "against_triggering_spell_same_turn",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.warlock.great-old-one.eldritch-hex",
            source_name="骇异恶咒",
            class_name="魔契师",
            subclass_name="旧日支配者宗主",
            level=10,
            source_record_id="b978fdb54062ecba2de9b056",
            source_excerpt_sha256=(
                "feac19dab4ad2b9ab670794887b8919c62fbe5b573900caf4598587bd6eadf39"
            ),
            clauses=[
                _clause(
                    "always-prepared-hex",
                    effects=[
                        {
                            "operator": "prepare_spell",
                            "parameters": {
                                "spell_id": "脆弱诅咒",
                                "source_class": "魔契师",
                                "preparation_mode": "always_prepared",
                            },
                        }
                    ],
                ),
                _clause(
                    "hex-chosen-ability-save-disadvantage",
                    trigger="saving_throw",
                    conditions=[
                        {
                            "kind": "target_has_state",
                            "parameters": {"state": "hexed_by_actor"},
                        },
                        {
                            "kind": "target_matches_persisted_id",
                            "parameters": {"key": "hex_target_id"},
                        },
                    ],
                    targeting={"kind": "enemy", "parameters": {}},
                    duration="until_condition_ends",
                    effects=[
                        {
                            "operator": "impose_disadvantage",
                            "parameters": {
                                "stat": "saving_throw",
                                "operation": "disadvantage",
                                "scope": "target",
                                "applies_when": "hex_selected_ability",
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.paladin.devotion.smite-of-protection",
            source_name="卫护斩",
            class_name="圣武士",
            subclass_name="奉献之誓",
            level=15,
            source_record_id="9d0cbb381195bdc22700ce7a",
            source_excerpt_sha256=(
                "7bb89dc3e1e4e48de956c868fc2209ae8d9863db4ad4f891b7c78b5dbe68d843"
            ),
            clauses=[
                _clause(
                    "smite-aura-half-cover",
                    trigger="spell_cast",
                    conditions=[
                        {
                            "kind": "action_tag",
                            "parameters": {"tag": "divine_smite"},
                        }
                    ],
                    targeting={
                        "kind": "aura",
                        "parameters": {"members": ["self", "allies"]},
                    },
                    duration="current_turn",
                    effects=[
                        {
                            "operator": "create_timed_modifier",
                            "parameters": {
                                "stat": "cover",
                                "operation": "set",
                                "value": 2,
                                "duration": "current_turn",
                                "scope": "aura",
                                "applies_when": "until_actor_next_turn_start",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.fighter.psi-warrior.bulwark-of-force",
            source_name="力场壁垒",
            class_name="战士",
            subclass_name="灵能武士",
            level=15,
            source_record_id="7af94ca3efa94531c62ee9dc",
            source_excerpt_sha256=(
                "3eceb79d2952141abb1220dbbd5d92024b9751f811a56babcf8b321d0f9b9519"
            ),
            clauses=[
                _clause(
                    "activate-half-cover",
                    trigger="explicit_activation",
                    activation="explicit_choice",
                    action_economy="bonus_action",
                    targeting={
                        "kind": "ally",
                        "parameters": {
                            "include_self": True,
                            "range_ft": 30,
                            "maximum": "intelligence_modifier_min_1",
                        },
                    },
                    duration="one_minute",
                    effects=[
                        {
                            "operator": "consume_resource",
                            "parameters": {
                                "resource_key": "bulwark_of_force",
                                "operation": "consume",
                                "amount": 1,
                            },
                        },
                        {
                            "operator": "create_timed_modifier",
                            "parameters": {
                                "stat": "cover",
                                "operation": "set",
                                "value": 2,
                                "duration": "one_minute",
                                "scope": "target",
                                "applies_when": "actor_not_incapacitated",
                            },
                        },
                    ],
                ),
                _clause(
                    "long-rest-recovery",
                    trigger="long_rest_completed",
                    effects=[
                        {
                            "operator": "restore_resource",
                            "parameters": {
                                "resource_key": "bulwark_of_force",
                                "operation": "set_to_max",
                                "amount": 1,
                            },
                        }
                    ],
                ),
                _clause(
                    "psi-die-reset",
                    trigger="explicit_activation",
                    activation="explicit_choice",
                    action_economy="none",
                    effects=[
                        {
                            "operator": "exchange_resource",
                            "parameters": {
                                "from_resource_key": "psi_energy_dice",
                                "to_resource_key": "bulwark_of_force",
                                "operation": "exchange",
                                "amount": 1,
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.barbarian.zealot.zealous-presence",
            source_name="狂热威仪",
            class_name="野蛮人",
            subclass_name="狂热者道途",
            level=10,
            source_record_id="56bade27e4a4f3f4977775a8",
            source_excerpt_sha256=(
                "08389de29da5e8b7db829102776c087eab44f6d9b03febce9ed82416f97e1172"
            ),
            clauses=[
                _clause(
                    "battle-cry",
                    trigger="explicit_activation",
                    activation="explicit_choice",
                    action_economy="bonus_action",
                    targeting={
                        "kind": "ally",
                        "parameters": {"range_ft": 60, "maximum": 10},
                    },
                    duration="current_turn",
                    effects=[
                        {
                            "operator": "consume_resource",
                            "parameters": {
                                "resource_key": "zealous_presence",
                                "operation": "consume",
                                "amount": 1,
                            },
                        },
                        {
                            "operator": "create_timed_modifier",
                            "parameters": {
                                "stat": "attack_roll",
                                "operation": "advantage",
                                "value": 1,
                                "duration": "current_turn",
                                "scope": "target",
                                "applies_when": "until_actor_next_turn_start",
                            },
                        },
                        {
                            "operator": "create_timed_modifier",
                            "parameters": {
                                "stat": "saving_throw",
                                "operation": "advantage",
                                "value": 1,
                                "duration": "current_turn",
                                "scope": "target",
                                "applies_when": "until_actor_next_turn_start",
                            },
                        },
                    ],
                ),
                _clause(
                    "long-rest-recovery",
                    trigger="long_rest_completed",
                    effects=[
                        {
                            "operator": "restore_resource",
                            "parameters": {
                                "resource_key": "zealous_presence",
                                "operation": "set_to_max",
                                "amount": 1,
                            },
                        }
                    ],
                ),
                _clause(
                    "rage-reset",
                    trigger="explicit_activation",
                    activation="explicit_choice",
                    action_economy="none",
                    effects=[
                        {
                            "operator": "exchange_resource",
                            "parameters": {
                                "from_resource_key": "rage",
                                "to_resource_key": "zealous_presence",
                                "operation": "exchange",
                                "amount": 1,
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.warlock.celestial.celestial-resilience",
            source_name="天界韧性",
            class_name="魔契师",
            subclass_name="天界宗主",
            level=10,
            source_record_id="180ee728207b19b5621a8eb9",
            source_excerpt_sha256=(
                "82b48fbec526d877d2a7659bc33fbfb4e1f2eda71538e6bc3337c37e8145c654"
            ),
            clauses=[
                _clause(
                    f"{trigger}-self-temporary-hp",
                    trigger=trigger,
                    targeting={"kind": "self", "parameters": {}},
                    effects=[
                        {
                            "operator": "grant_temporary_hp",
                            "parameters": {
                                "formula": "warlock_level+charisma_modifier",
                                "source": "celestial_resilience",
                            },
                        }
                    ],
                )
                for trigger in (
                    "short_rest_completed",
                    "long_rest_completed",
                    "explicit_activation",
                )
            ]
            + [
                _clause(
                    f"{trigger}-allies-temporary-hp",
                    trigger=trigger,
                    targeting={
                        "kind": "ally",
                        "parameters": {
                            "visible": True,
                            "maximum": 5,
                        },
                    },
                    effects=[
                        {
                            "operator": "grant_temporary_hp",
                            "parameters": {
                                "formula": "floor(warlock_level/2)+charisma_modifier",
                                "source": "celestial_resilience",
                            },
                        }
                    ],
                )
                for trigger in (
                    "short_rest_completed",
                    "long_rest_completed",
                    "explicit_activation",
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.rogue.assassin.assassinate",
            source_name="暗杀",
            class_name="游荡者",
            subclass_name="刺客",
            level=3,
            source_record_id="ed19d790590e092a37804fdc",
            source_excerpt_sha256=(
                "9375a91a0dddc2a575a038176321cac18985c4a0861b6fd6b2eb64799a9da542"
            ),
            clauses=[
                _clause(
                    "initiative-advantage",
                    trigger="initiative_rolled",
                    duration="current_round",
                    effects=[
                        {
                            "operator": "impose_advantage",
                            "parameters": {
                                "stat": "initiative",
                                "operation": "advantage",
                                "scope": "self",
                                "applies_when": "initiative_roll",
                            },
                        }
                    ],
                ),
                _clause(
                    "first-round-attack-advantage",
                    trigger="attack_declared",
                    conditions=[
                        {"kind": "first_round", "parameters": {}},
                        {"kind": "target_has_not_acted", "parameters": {}},
                    ],
                    duration="current_round",
                    effects=[
                        {
                            "operator": "impose_advantage",
                            "parameters": {
                                "stat": "attack_roll",
                                "operation": "advantage",
                                "scope": "outgoing",
                                "applies_when": "target_has_not_acted_first_round",
                            },
                        }
                    ],
                ),
                _clause(
                    "first-round-sneak-attack-damage",
                    trigger="attack_hit",
                    conditions=[
                        {"kind": "first_round", "parameters": {}},
                        {"kind": "target_has_not_acted", "parameters": {}},
                        {
                            "kind": "action_tag",
                            "parameters": {"tag": "sneak_attack"},
                        },
                        {"kind": "once_per_target", "parameters": {}},
                    ],
                    targeting={"kind": "enemy", "parameters": {}},
                    duration="current_round",
                    effects=[
                        {
                            "operator": "add_damage",
                            "parameters": {
                                "formula": "rogue_level",
                                "damage_type": "weapon_damage_type",
                                "applies_when": "first_round_sneak_attack",
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.druid.moon.improved-circle-forms",
            source_name="进阶结社形态",
            class_name="德鲁伊",
            subclass_name="月亮结社",
            level=6,
            source_record_id="4e1a16417129f0809deb556c",
            source_excerpt_sha256=(
                "00c7b7dc1541c66f6f8d18036f16ec6c2667862f52fc983bb685f27b8a2af78e"
            ),
            clauses=[
                _clause(
                    "wild-shape-radiant-damage-choice",
                    trigger="damage_before_apply",
                    conditions=[
                        {
                            "kind": "actor_has_state",
                            "parameters": {"state": "wild_shape"},
                        }
                    ],
                    targeting={"kind": "enemy", "parameters": {}},
                    duration="advancement_persistent",
                    required_inputs=[
                        {
                            "key": "wild_shape_damage_type",
                            "kind": "choice",
                            "parameters": {
                                "options": ["normal", "radiant"],
                                "requires_ui": "damage_type_choice",
                            },
                        }
                    ],
                    effects=[
                        {
                            "operator": "replace_damage_type",
                            "parameters": {
                                "from_type": "wild_shape_attack_damage_type",
                                "to_type": "radiant",
                                "applies_when": "player_selects_radiant",
                            },
                        }
                    ],
                ),
                _clause(
                    "wild-shape-constitution-save-bonus",
                    trigger="saving_throw",
                    conditions=[
                        {
                            "kind": "actor_has_state",
                            "parameters": {"state": "wild_shape"},
                        }
                    ],
                    duration="advancement_persistent",
                    effects=[
                        {
                            "operator": "add_modifier",
                            "parameters": {
                                "stat": "constitution_saving_throw",
                                "operation": "add",
                                "value_source": "wisdom_modifier",
                                "scope": "self",
                                "applies_when": "actor_in_wild_shape",
                            },
                        }
                    ],
                ),
            ],
        ),
    )
