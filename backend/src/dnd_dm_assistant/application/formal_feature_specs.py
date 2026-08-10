"""Authored Feature IR for the first production migration cohort.

The registry is content data: stable IDs bind a source record to a typed IR
spec.  Runtime executors consume the compiled/materialized contract and never
branch on these names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from dnd_dm_assistant.domain.feature_ir import FeatureSpec

PACK_ID = "2024-core-formal"
PACK_VERSION = "1.0.0"
RULESET_VERSION = "2024"


def _feature(
    feature_id: str,
    *,
    source_name: str,
    class_name: str,
    level: int,
    subclass_name: str | None = None,
    source_record_id: str | None = None,
    source_trust: str = "authored_ir",
    clauses: list[dict[str, Any]],
) -> FeatureSpec:
    return FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": feature_id,
            "namespace": "dnd.2024.core",
            "pack_id": PACK_ID,
            "pack_version": PACK_VERSION,
            "ruleset_version": RULESET_VERSION,
            "source_record_id": source_record_id or feature_id,
            "source_name": source_name,
            "source_trust": source_trust,
            "localized_names": {"zh-CN": source_name},
            "class_name": class_name,
            "subclass_name": subclass_name,
            "level": level,
            "source_completeness": "complete",
            "clauses": clauses,
            "dependencies": [],
            "compatibility": {"runtime_source": "feature_ir"},
        },
        path=f"formal_feature:{feature_id}",
    )


def _clause(clause_id: str, *, effects: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {
        "clause_id": clause_id,
        "trigger": "advancement_confirmed",
        "conditions": [],
        "activation": "automatic",
        "action_economy": "none",
        "resource_costs": [],
        "resource_recovery": [],
        "required_inputs": [],
        "targeting": {"kind": "self", "parameters": {}},
        "effects": effects,
        "duration": "advancement_persistent",
        "expiry": None,
        "stacking": None,
        "frequency": None,
        "persistence": "character.feature_runtime",
        "visibility": "owner",
        "audit": {"source": "authored_ir"},
        **overrides,
    }


def formal_feature_specs() -> tuple[FeatureSpec, ...]:
    return (
        _feature(
            "dnd2024.core.druid.druidic",
            source_name="德鲁伊语",
            class_name="德鲁伊",
            level=1,
            source_record_id="30c6d89fdef6d38670fe099f",
            clauses=[
                _clause(
                    "language",
                    effects=[
                        {
                            "operator": "grant_language",
                            "parameters": {
                                "language_id": "druidic",
                                "operation": "grant",
                            },
                        }
                    ],
                ),
                _clause(
                    "animal-speech",
                    effects=[
                        {
                            "operator": "grant_spell",
                            "parameters": {
                                "spell_id": "动物交谈",
                                "source_class": "德鲁伊",
                                "casting_ability": "wisdom",
                                "grant_mode": "known",
                                "ritual_only": True,
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.core.rogue.thieves-cant",
            source_name="盗贼黑话",
            class_name="游荡者",
            level=1,
            source_record_id="fb532140be89442c2e61bbc3",
            clauses=[
                _clause(
                    "cant-language",
                    effects=[
                        {
                            "operator": "grant_language",
                            "parameters": {
                                "language_id": "thieves_cant",
                                "operation": "grant",
                            },
                        }
                    ],
                ),
                _clause(
                    "ordinary-language-choice",
                    effects=[
                        {
                            "operator": "grant_proficiency",
                            "parameters": {
                                "proficiency_kind": "language_choice",
                                "asset_id": "core_languages",
                                "operation": "grant",
                            },
                        }
                    ],
                    required_inputs=[
                        {
                            "key": "language_choice",
                            "kind": "choice",
                            "parameters": {
                                "options_source": "core_languages",
                                "duplicate_policy": "forbid",
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.core.warlock.contact-patron",
            source_name="联络宗主",
            class_name="魔契师",
            level=9,
            source_record_id="0004fc526ac05c727b45c494",
            clauses=[
                _clause(
                    "spell",
                    effects=[
                        {
                            "operator": "grant_spell",
                            "parameters": {
                                "spell_id": "异界探知",
                                "source_class": "魔契师",
                                "casting_ability": "charisma",
                                "grant_mode": "free_cast",
                                "free_cast_resource_key": "contact_other_plane",
                                "auto_save": True,
                            },
                        }
                    ],
                ),
                _clause(
                    "recovery",
                    trigger="long_rest_completed",
                    effects=[
                        {
                            "operator": "restore_resource",
                            "parameters": {
                                "resource_key": "contact_other_plane",
                                "operation": "set_to_max",
                                "amount": 1,
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.core.ranger.roving",
            source_name="越野",
            class_name="游侠",
            level=6,
            source_record_id="e713e24b67b304ea682f4f79",
            clauses=[
                _clause(
                    "speed",
                    effects=[
                        {
                            "operator": "add_modifier",
                            "parameters": {
                                "stat": "speed_ft",
                                "operation": "add",
                                "value": 10,
                                "scope": "self",
                                "applies_when": "not_wearing_heavy_armor",
                                "id": "roving:speed_bonus",
                            },
                        }
                    ],
                ),
                _clause(
                    "climb",
                    effects=[
                        {
                            "operator": "grant_movement_mode",
                            "parameters": {
                                "mode": "climb",
                                "speed_source": "current_speed",
                                "requires_not_wearing_heavy_armor": True,
                                "id": "roving:climb_speed",
                            },
                        }
                    ],
                ),
                _clause(
                    "swim",
                    effects=[
                        {
                            "operator": "grant_movement_mode",
                            "parameters": {
                                "mode": "swim",
                                "speed_source": "current_speed",
                                "requires_not_wearing_heavy_armor": True,
                                "id": "roving:swim_speed",
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.core.ranger.wild-senses",
            source_name="野性感官",
            class_name="游侠",
            level=18,
            source_record_id="e713e24b67b304ea682f4f79",
            clauses=[
                _clause(
                    "blindsight",
                    effects=[
                        {
                            "operator": "grant_sight_mode",
                            "parameters": {
                                "mode": "blindsight",
                                "range_ft": 30,
                                "applies_when": "always",
                                "id": "wild_senses:blindsight",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.rogue.thief.second-story-work",
            source_name="梁上君子",
            class_name="游荡者",
            subclass_name="盗贼",
            level=3,
            source_record_id="02b8aab50780da6346807dfc",
            clauses=[
                _clause(
                    "jump",
                    effects=[
                        {
                            "operator": "set_modifier",
                            "parameters": {
                                "stat": "jump_ability",
                                "operation": "set",
                                "value_source": "dexterity",
                                "scope": "self",
                                "applies_when": "always",
                                "id": "second_story_work:jump_ability",
                            },
                        }
                    ],
                ),
                _clause(
                    "climb",
                    effects=[
                        {
                            "operator": "grant_movement_mode",
                            "parameters": {
                                "mode": "climb",
                                "speed_source": "current_speed",
                                "id": "second_story_work:climb_speed",
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.cleric.life.disciple-of-life",
            source_name="生命门徒",
            class_name="牧师",
            subclass_name="生命领域",
            level=3,
            source_record_id="416f4d85cbfd5602a831bd30",
            clauses=[
                _clause(
                    "healing",
                    effects=[
                        {
                            "operator": "spell_healing_modifier",
                            "parameters": {
                                "operation": "add",
                                "formula": "spell_slot_level_plus_two",
                                "applies_when": "legal_spell_healing_source",
                                "id": "life_domain:spell_healing",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.wizard.evoker.empowered-evocation",
            source_name="强效塑能",
            class_name="法师",
            subclass_name="塑能师",
            level=10,
            source_record_id="246f0d90218413f43cbdd155",
            clauses=[
                _clause(
                    "damage",
                    effects=[
                        {
                            "operator": "spell_damage_modifier",
                            "parameters": {
                                "operation": "add_ability_modifier_once",
                                "formula": "ability_modifier",
                                "ability": "intelligence",
                                "spell_school": "evocation",
                                "applies_when": "legal_evocation_spell_damage",
                                "id": "empowered_evocation:spell_damage_ability",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.wizard.evoker.potent-cantrip",
            source_name="强力戏法",
            class_name="法师",
            subclass_name="塑能师",
            level=3,
            source_record_id="246f0d90218413f43cbdd155",
            clauses=[
                _clause(
                    "save-failure",
                    effects=[
                        {
                            "operator": "spell_save_damage_modifier",
                            "parameters": {
                                "operation": "cantrip_failure_half",
                                "formula": "half_damage",
                                "spell_school": "evocation",
                                "applies_when": "cantrip_save_failure",
                                "id": "potent_cantrip:failure_half_damage",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.paladin.ancients.undying-sentinel",
            source_name="不灭哨卫",
            class_name="圣武士",
            subclass_name="古贤之誓",
            level=15,
            source_record_id="09860de59419ccc7f1b12908",
            clauses=[
                _clause(
                    "zero-hp",
                    trigger="damage_before_apply",
                    duration="until_long_rest",
                    effects=[
                        {
                            "operator": "zero_hp_intervention",
                            "parameters": {
                                "trigger": "would_drop_to_zero_hit_points",
                                "replacement_hp": "3*paladin_level",
                                "resource_key": "undying_sentinel",
                                "eligibility": {
                                    "entity_types": ["character"],
                                    "class_names": ["圣武士", "paladin"],
                                    "minimum_level": 15,
                                },
                                "reset": "long_rest",
                                "exceptions": ["outright_death"],
                                "id": "undying_sentinel:zero_hp_prevention",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.paladin.vengeance.vow-of-enmity",
            source_name="仇敌誓言",
            class_name="圣武士",
            subclass_name="复仇之誓",
            level=3,
            source_record_id="verified:vow-of-enmity",
            source_trust="verified_mapping",
            clauses=[
                _clause(
                    "targeted-advantage",
                    trigger="action_declared",
                    activation="explicit_choice",
                    action_economy="none",
                    targeting={"kind": "enemy", "parameters": {"range_ft": 30}},
                    duration="one_minute",
                    conditions=[{"kind": "visible", "parameters": {}}],
                    effects=[
                        {
                            "operator": "impose_advantage",
                            "parameters": {
                                "stat": "attack_roll",
                                "operation": "advantage",
                                "scope": "outgoing",
                                "applies_when": "target_matches_persisted_id",
                                "id": "vow_of_enmity:attack_advantage",
                            },
                        }
                    ],
                ),
                _clause(
                    "retarget-recovery",
                    trigger="zero_hp",
                    effects=[
                        {
                            "operator": "restore_resource",
                            "parameters": {
                                "resource_key": "channel_divinity",
                                "operation": "set_to_max",
                                "amount": 1,
                            },
                        }
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.paladin.vengeance.soul-of-vengeance",
            source_name="复仇之魂",
            class_name="圣武士",
            subclass_name="复仇之誓",
            level=15,
            source_record_id="verified:soul-of-vengeance",
            source_trust="verified_mapping",
            clauses=[
                _clause(
                    "triggered-reaction-attack",
                    activation="automatic",
                    action_economy="reaction",
                    targeting={
                        "kind": "enemy",
                        "parameters": {"range": "weapon_reach"},
                    },
                    duration="current_turn",
                    trigger="action_resolved",
                    conditions=[
                        {"kind": "target_matches_persisted_id", "parameters": {}}
                    ],
                    effects=[
                        {
                            "operator": "create_triggered_attack_window",
                            "parameters": {
                                "window_kind": "soul_of_vengeance",
                                "parent_action": "enemy_attack",
                                "target_policy": {
                                    "mode": "event_actor",
                                    "range_ft": "weapon_reach",
                                    "requires_visible_or_audible": True,
                                },
                                "expires": "current_turn",
                                "reaction_type": "reaction",
                                "attack_profile": {"mode": "melee_weapon_only"},
                                "id": "soul_of_vengeance:triggered_attack",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.paladin.glory.peerless-athlete",
            source_name="绝伦健将",
            class_name="圣武士",
            subclass_name="荣耀之誓",
            level=3,
            source_record_id="verified:peerless-athlete",
            source_trust="verified_mapping",
            clauses=[
                _clause(
                    "peerless-athlete-activation",
                    trigger="explicit_activation",
                    activation="explicit_choice",
                    action_economy="bonus_action",
                    duration="one_hour",
                    effects=[
                        {
                            "operator": "consume_resource",
                            "parameters": {
                                "resource_key": "channel_divinity",
                                "operation": "consume",
                                "amount": 1,
                            },
                        },
                        {
                            "operator": "create_timed_modifier",
                            "parameters": {
                                "stat": "skill_check",
                                "operation": "advantage",
                                "duration": "one_hour",
                                "scope": "self",
                                "applies_when": "skill:运动",
                                "value": 1,
                                "id": "peerless_athlete:athletics",
                            },
                        },
                        {
                            "operator": "create_timed_modifier",
                            "parameters": {
                                "stat": "skill_check",
                                "operation": "advantage",
                                "duration": "one_hour",
                                "scope": "self",
                                "applies_when": "skill:特技",
                                "value": 1,
                                "id": "peerless_athlete:acrobatics",
                            },
                        },
                        {
                            "operator": "create_timed_modifier",
                            "parameters": {
                                "stat": "jump_distance_ft",
                                "operation": "add",
                                "duration": "one_hour",
                                "scope": "self",
                                "value": 10,
                                "id": "peerless_athlete:jump",
                            },
                        },
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.fighter.battle-master.ultimate-combat",
            source_name="究极战技",
            class_name="战士",
            subclass_name="战斗大师",
            level=18,
            source_record_id="verified:ultimate-combat",
            source_trust="verified_mapping",
            clauses=[
                _clause(
                    "superiority-die-profile",
                    effects=[
                        {
                            "operator": "set_resource_profile",
                            "parameters": {
                                "resource_key": "superiority_dice",
                                "resource_kind": "superiority_dice",
                                "die_size": 12,
                                "max_formula": "battle_master_superiority_dice_table",
                                "id": "ultimate_combat:superiority_die",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.barbarian.zealot.divine-rage",
            source_name="神之狂暴",
            class_name="野蛮人",
            subclass_name="狂热者道途",
            level=14,
            source_record_id="verified:divine-rage",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "activate",
                    trigger="explicit_activation",
                    activation="explicit_choice",
                    action_economy="bonus_action",
                    duration="one_minute",
                    effects=[
                        {
                            "operator": "consume_resource",
                            "parameters": {
                                "resource_key": "divine_rage",
                                "operation": "consume",
                                "amount": 1,
                            },
                        },
                        {
                            "operator": "activate_condition",
                            "parameters": {
                                "condition": "divine_rage",
                                "duration": "one_minute",
                                "id": "divine_rage:state",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "necrotic",
                                "applies_when": "divine_rage",
                                "id": "divine_rage:necrotic",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "psychic",
                                "applies_when": "divine_rage",
                                "id": "divine_rage:psychic",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "radiant",
                                "applies_when": "divine_rage",
                                "id": "divine_rage:radiant",
                            },
                        },
                        {
                            "operator": "grant_movement_mode",
                            "parameters": {
                                "mode": "fly",
                                "speed_source": "current_speed",
                                "applies_when": "divine_rage",
                                "id": "divine_rage:flight",
                            },
                        },
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.bard.college-of-dance.dance-virtuoso",
            source_name="炫目舞步",
            class_name="吟游诗人",
            subclass_name="舞蹈学院",
            level=3,
            source_record_id="verified:dance-virtuoso",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "unarmored-defense",
                    effects=[
                        {
                            "operator": "grant_passive_modifier",
                            "parameters": {
                                "stat": "armor_class",
                                "operation": "set_base_formula",
                                "formula": "10+dexterity_modifier+charisma_modifier",
                                "scope": "self",
                                "applies_when": "not_wearing_armor",
                                "value": 1,
                                "id": "dance_virtuoso:ac",
                            },
                        },
                        {
                            "operator": "grant_passive_modifier",
                            "parameters": {
                                "stat": "ability_check",
                                "operation": "advantage",
                                "scope": "self",
                                "applies_when": "every_charisma_ability_check",
                                "value": 1,
                                "id": "dance_virtuoso:performance",
                            },
                        },
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.bard.college-of-valor.combat-inspiration",
            source_name="战斗激励Combat Inspiration",
            class_name="吟游诗人",
            subclass_name="勇气学院",
            level=3,
            source_record_id="2709144090ad73a4c316bfe6",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "combat-inspiration",
                    effects=[
                        {
                            "operator": "configure_attack_roll_intervention",
                            "parameters": {
                                "source_die_key": "bardic_inspiration_die",
                                "modes": ["defense", "offense"],
                                "id": "combat_inspiration",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.ranger.hunter.hunters-lore",
            source_name="猎人学识 Hunter's Lore",
            class_name="游侠",
            subclass_name="猎人",
            level=3,
            source_record_id="verified:hunters-lore",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "inspect-marked-target-defenses",
                    trigger="explicit_activation",
                    activation="explicit_choice",
                    targeting={
                        "kind": "enemy",
                        "parameters": {"requires_visible_or_audible": True},
                    },
                    duration="current_turn",
                    conditions=[
                        {"kind": "target_matches_persisted_id", "parameters": {}}
                    ],
                    effects=[
                        {
                            "operator": "expose_authorized_target_information",
                            "parameters": {
                                "information_kind": "damage_defenses",
                                "required_state_target_key": "current_hunters_mark_target_id",
                                "id": "hunters_lore:damage_defenses",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.warlock.aberrant-mind.psychic-defenses",
            source_name="心灵防御 Psychic",
            class_name="术士",
            subclass_name="畸变术法",
            level=6,
            source_record_id="0d93a792867dfff4a2f40402",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "psychic-resistance-and-condition-saves",
                    effects=[
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "psychic",
                                "id": "psychic_defenses:psychic_resistance",
                            },
                        },
                        {
                            "operator": "grant_passive_modifier",
                            "parameters": {
                                "stat": "saving_throw",
                                "operation": "advantage",
                                "value": 1,
                                "scope": "self",
                                "applies_when": "saving_throw_against_charmed_or_frightened",
                                "id": "psychic_defenses:condition_save_advantage",
                            },
                        },
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.fighter.champion.superior-critical",
            source_name="高效重击 Superior",
            class_name="战士",
            subclass_name="勇士",
            level=15,
            source_record_id="fa4052ed9e53e0d32483d691",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "critical-threshold",
                    effects=[
                        {
                            "operator": "set_modifier",
                            "parameters": {
                                "stat": "attack_critical_threshold",
                                "operation": "set",
                                "value": 18,
                                "scope": "outgoing",
                                "applies_when": "always",
                                "id": "critical_threshold:18",
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.monk.way-of-mercy.implements",
            source_name="操命本事 Implements of",
            class_name="武僧",
            subclass_name="命流武者",
            level=3,
            source_record_id="eea779c8a7bdd0ca384fede5",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "fixed-proficiencies",
                    effects=[
                        {
                            "operator": "grant_proficiency",
                            "parameters": {
                                "proficiency_kind": "skill",
                                "asset_id": "洞悉",
                                "operation": "grant",
                            },
                        },
                        {
                            "operator": "grant_proficiency",
                            "parameters": {
                                "proficiency_kind": "skill",
                                "asset_id": "医药",
                                "operation": "grant",
                            },
                        },
                        {
                            "operator": "grant_proficiency",
                            "parameters": {
                                "proficiency_kind": "tool",
                                "asset_id": "草药工具",
                                "operation": "grant",
                            },
                        },
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.rogue.assassin.assassins-tools",
            source_name="刺客工具 Assassin's",
            class_name="游荡者",
            subclass_name="刺客",
            level=3,
            source_record_id="ed19d790590e092a37804fdc",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "fixed-tool-proficiencies",
                    effects=[
                        {
                            "operator": "grant_proficiency",
                            "parameters": {
                                "proficiency_kind": "tool",
                                "asset_id": "易容工具",
                                "operation": "grant",
                            },
                        },
                        {
                            "operator": "grant_proficiency",
                            "parameters": {
                                "proficiency_kind": "tool",
                                "asset_id": "毒药工具",
                                "operation": "grant",
                            },
                        },
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.wizard.abjurer.spell-resistance",
            source_name="法术抗性 Spell Resistance",
            class_name="法师",
            subclass_name="防护师",
            level=14,
            source_record_id="655461c88c4fe6cf243214",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "magical-saving-throws",
                    effects=[
                        {
                            "operator": "grant_saving_throw_advantage",
                            "parameters": {
                                "applies_when": "magical",
                                "id": "spell_resistance:magical_saves",
                            },
                        }
                    ],
                ),
                _clause(
                    "magical-damage-resistance",
                    effects=[
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "acid",
                                "applies_when": "magical",
                                "id": "spell_resistance:acid",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "bludgeoning",
                                "applies_when": "magical",
                                "id": "spell_resistance:bludgeoning",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "cold",
                                "applies_when": "magical",
                                "id": "spell_resistance:cold",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "fire",
                                "applies_when": "magical",
                                "id": "spell_resistance:fire",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "force",
                                "applies_when": "magical",
                                "id": "spell_resistance:force",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "lightning",
                                "applies_when": "magical",
                                "id": "spell_resistance:lightning",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "necrotic",
                                "applies_when": "magical",
                                "id": "spell_resistance:necrotic",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "piercing",
                                "applies_when": "magical",
                                "id": "spell_resistance:piercing",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "poison",
                                "applies_when": "magical",
                                "id": "spell_resistance:poison",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "psychic",
                                "applies_when": "magical",
                                "id": "spell_resistance:psychic",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "radiant",
                                "applies_when": "magical",
                                "id": "spell_resistance:radiant",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "slashing",
                                "applies_when": "magical",
                                "id": "spell_resistance:slashing",
                            },
                        },
                        {
                            "operator": "grant_resistance",
                            "parameters": {
                                "damage_type": "thunder",
                                "applies_when": "magical",
                                "id": "spell_resistance:thunder",
                            },
                        },
                    ],
                ),
            ],
        ),
        _feature(
            "dnd2024.subclass.fighter.psi-warrior.psionic-power",
            source_name="灵能力量 Psionic",
            class_name="战士",
            subclass_name="灵能武士",
            level=3,
            source_record_id="verified:psi-warrior-psionic-power",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "psionic-die-profile",
                    effects=[
                        {
                            "operator": "set_resource_profile",
                            "parameters": {
                                "resource_key": "$feature_resource",
                                "resource_kind": "psionic_dice",
                                "die_size": 6,
                                "max_formula": "psionic_dice_table",
                                "recovery_events": [
                                    {
                                        "rest": "short_rest",
                                        "operation": "restore",
                                        "amount": 1,
                                    },
                                    {"rest": "long_rest", "operation": "set_to_max"},
                                ],
                            },
                        }
                    ],
                )
            ],
        ),
        _feature(
            "dnd2024.subclass.rogue.soulknife.psionic-power",
            source_name="灵能力量 Psionic",
            class_name="游荡者",
            subclass_name="魂刃",
            level=3,
            source_record_id="verified:soulknife-psionic-power",
            source_trust="authored_ir",
            clauses=[
                _clause(
                    "psionic-die-profile",
                    effects=[
                        {
                            "operator": "set_resource_profile",
                            "parameters": {
                                "resource_key": "$feature_resource",
                                "resource_kind": "psionic_dice",
                                "die_size": 6,
                                "max_formula": "psionic_dice_table",
                                "recovery_events": [
                                    {
                                        "rest": "short_rest",
                                        "operation": "restore",
                                        "amount": 1,
                                    },
                                    {"rest": "long_rest", "operation": "set_to_max"},
                                ],
                            },
                        }
                    ],
                )
            ],
        ),
    )


_ALIASES: dict[tuple[str, str | None, str], str] = {
    ("德鲁伊", None, "德鲁伊语"): "dnd2024.core.druid.druidic",
    ("游荡者", None, "盗贼黑话"): "dnd2024.core.rogue.thieves-cant",
    ("魔契师", None, "联络宗主"): "dnd2024.core.warlock.contact-patron",
    ("游侠", None, "越野"): "dnd2024.core.ranger.roving",
    ("游侠", None, "野性感官"): "dnd2024.core.ranger.wild-senses",
    ("游荡者", "盗贼", "梁上君子"): "dnd2024.subclass.rogue.thief.second-story-work",
    ("牧师", "生命领域", "生命门徒"): "dnd2024.subclass.cleric.life.disciple-of-life",
    ("法师", "塑能师", "强效塑能"): "dnd2024.subclass.wizard.evoker.empowered-evocation",
    ("法师", "塑能师", "强力戏法"): "dnd2024.subclass.wizard.evoker.potent-cantrip",
    ("圣武士", "古贤之誓", "不灭哨卫"): "dnd2024.subclass.paladin.ancients.undying-sentinel",
    ("圣武士", "复仇之誓", "仇敌誓言"): "dnd2024.subclass.paladin.vengeance.vow-of-enmity",
    ("圣武士", "复仇之誓", "复仇之魂"): "dnd2024.subclass.paladin.vengeance.soul-of-vengeance",
    ("圣武士", "荣耀之誓", "绝伦健将"): "dnd2024.subclass.paladin.glory.peerless-athlete",
    ("战士", "战斗大师", "究极战技"): "dnd2024.subclass.fighter.battle-master.ultimate-combat",
    ("野蛮人", "狂热者道途", "神之狂暴"): "dnd2024.subclass.barbarian.zealot.divine-rage",
    ("吟游诗人", "舞蹈学院", "炫目舞步"): "dnd2024.subclass.bard.college-of-dance.dance-virtuoso",
    ("吟游诗人", "勇气学院", "战斗激励"): (
        "dnd2024.subclass.bard.college-of-valor.combat-inspiration"
    ),
    ("游侠", "猎人", "猎人学识"): "dnd2024.subclass.ranger.hunter.hunters-lore",
    ("术士", "畸变术法", "心灵防御"): "dnd2024.subclass.warlock.aberrant-mind.psychic-defenses",
    ("战士", "勇士", "高效重击"): "dnd2024.subclass.fighter.champion.superior-critical",
    ("武僧", "命流武者", "操命本事"): "dnd2024.subclass.monk.way-of-mercy.implements",
    ("游荡者", "刺客", "刺客工具"): "dnd2024.subclass.rogue.assassin.assassins-tools",
    ("法师", "防护师", "法术抗性"): "dnd2024.subclass.wizard.abjurer.spell-resistance",
    ("战士", "灵能武士", "灵能力量"): "dnd2024.subclass.fighter.psi-warrior.psionic-power",
    ("游荡者", "魂刃", "灵能力量"): "dnd2024.subclass.rogue.soulknife.psionic-power",
}

_SOURCE_ALIASES: dict[str, str] = {
    "Second-Story": "梁上君子",
    "Disciple of": "生命门徒",
    "Empowered Evocation": "强效塑能",
    "Potent Cantrip": "强力戏法",
    "Undying": "不灭哨卫",
    "Vow of": "仇敌誓言",
    "Soul of": "复仇之魂",
    "Ultimate Combat": "究极战技",
    "Peerless Athlete": "绝伦健将",
    "Peerless": "绝伦健将",
    "Rage of the Gods": "神之狂暴",
    "Rage of the": "神之狂暴",
    "Dazzling Footwork": "炫目舞步",
    "战斗激励Combat Inspiration": "战斗激励",
    "猎人学识 Hunter's Lore": "猎人学识",
    "猎人学识 Hunter's": "猎人学识",
    "心灵防御 Psychic": "心灵防御",
    "究极战技 Ultimate Combat": "究极战技",
    "高效重击 Superior": "高效重击",
    "操命本事 Implements of": "操命本事",
    "刺客工具 Assassin's": "刺客工具",
    "法术抗性 Spell Resistance": "法术抗性",
    "灵能力量 Psionic": "灵能力量",
}


def formal_feature_specs_by_id() -> dict[str, FeatureSpec]:
    return {spec.feature_id: spec for spec in formal_feature_specs()}


def formal_feature_spec_for_definition(
    definition: Mapping[str, Any],
) -> FeatureSpec | None:
    class_name = str(definition.get("class_name") or "").strip()
    subclass_name = str(definition.get("subclass_name") or "").strip() or None
    source_name = str(definition.get("name") or definition.get("feature_name") or "").strip()
    localized_name = _SOURCE_ALIASES.get(source_name, source_name)
    if localized_name == source_name:
        for alias, canonical in _SOURCE_ALIASES.items():
            if source_name.endswith(alias) or alias in source_name:
                localized_name = canonical
                break
    feature_id = _ALIASES.get((class_name, subclass_name, localized_name))
    if feature_id is None:
        return None
    spec = formal_feature_specs_by_id()[feature_id]
    return replace(
        spec,
        source_name=source_name,
        source_record_id=str(definition.get("source_record_id") or spec.source_record_id),
        localized_names={"zh-CN": localized_name, "source": source_name},
        level=int(definition.get("class_level") or definition.get("level") or spec.level or 0),
    )
