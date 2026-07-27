from __future__ import annotations

from typing import Any, Literal

EquipmentSlot = Literal["armor", "main_hand", "off_hand", "focus", "worn"]

ARMOR_NAMES: dict[str, tuple[str, int]] = {
    "衬垫甲": ("light", 11),
    "皮甲": ("light", 11),
    "镶钉皮甲": ("light", 12),
    "兽皮甲": ("medium", 12),
    "链甲衫": ("medium", 13),
    "鳞甲": ("medium", 14),
    "胸甲": ("medium", 14),
    "半身板甲": ("medium", 15),
    "环甲": ("heavy", 14),
    "链甲": ("heavy", 16),
    "板条甲": ("heavy", 17),
    "板甲": ("heavy", 18),
}
TWO_HANDED_NAMES = {
    "巨棒",
    "长柄刀",
    "巨斧",
    "巨剑",
    "戟",
    "大锤",
    "长枪",
    "长弓",
    "重弩",
}
FOCUS_WORDS = ("法器", "圣徽", "法杖", "魔杖", "乐器", "工具")
WEAPON_WORDS = (
    "剑",
    "弓",
    "弩",
    "斧",
    "锤",
    "匕首",
    "长矛",
    "短棍",
    "巨棒",
    "戟",
    "长枪",
    "法杖",
)


def equipment_profile(
    name: str,
    category: str = "gear",
    metadata: dict[str, Any] | None = None,
    armor_class: int | None = None,
) -> dict[str, Any]:
    """Return a conservative 5e equipment profile without inventing MMO body slots."""

    metadata = dict(metadata or {})
    text = f"{name} {metadata.get('description', '')} {metadata.get('properties', '')}"
    explicit_kind = str(metadata.get("equipment_kind") or "").lower()
    armor_name = next((key for key in ARMOR_NAMES if key in name), None)
    armor_type = str(metadata.get("armor_type") or "")
    if not armor_type and armor_name:
        armor_type = ARMOR_NAMES[armor_name][0]
    is_shield = explicit_kind == "shield" or "盾牌" in name or name.endswith("盾")
    is_armor = (
        explicit_kind == "armor"
        or category == "armor"
        or armor_name is not None
        or armor_type in {"light", "medium", "heavy"}
    ) and not is_shield
    is_weapon = (
        explicit_kind == "weapon"
        or category == "weapon"
        or any(word in name for word in WEAPON_WORDS)
    ) and not is_armor and not is_shield
    is_focus = explicit_kind in {"focus", "tool"} or any(word in name for word in FOCUS_WORDS)
    two_handed = bool(metadata.get("two_handed")) or "双手" in text or any(
        weapon in name for weapon in TWO_HANDED_NAMES
    )

    if is_armor:
        allowed_slots: list[EquipmentSlot] = ["armor"]
        kind = "armor"
        hand_usage = 0
    elif is_shield:
        allowed_slots = ["off_hand"]
        kind = "shield"
        hand_usage = 1
    elif is_weapon:
        allowed_slots = ["main_hand"] if two_handed else ["main_hand", "off_hand"]
        kind = "weapon"
        hand_usage = 2 if two_handed else 1
    elif is_focus:
        allowed_slots = ["focus", "main_hand", "off_hand"]
        kind = "focus"
        hand_usage = 1
    else:
        allowed_slots = ["worn"]
        kind = "worn"
        hand_usage = 0

    inferred_ac = armor_class
    if inferred_ac is None and armor_name:
        inferred_ac = ARMOR_NAMES[armor_name][1]
    return {
        "kind": kind,
        "allowed_slots": allowed_slots,
        "default_slot": allowed_slots[0],
        "hand_usage": hand_usage,
        "two_handed": two_handed,
        "armor_type": armor_type or None,
        "base_armor_class": inferred_ac,
        "rule_reference": "D&D 5e 2024 PHB · Armor / Weapons / Equipment",
    }


def armor_is_proficient(proficiencies: list[object], armor_type: str | None) -> bool:
    labels = {str(value) for value in proficiencies}
    if armor_type == "light":
        return "轻甲" in labels or "所有护甲" in labels
    if armor_type == "medium":
        return "中甲" in labels or "所有护甲" in labels
    if armor_type == "heavy":
        return "重甲" in labels or "所有护甲" in labels
    return False


def weapon_proficiency_warning(name: str, proficiencies: list[object]) -> str | None:
    labels = {str(value) for value in proficiencies}
    if any(value in labels for value in ("简易武器", "军用武器", "灵巧武器", "轻型军用武器")):
        return None
    return f"可以持握{name}，但角色未记录相应武器熟练；攻击检定不得加入熟练加值。"


def armor_class_from_profile(
    profile: dict[str, Any], dexterity_modifier: int
) -> int | None:
    base = profile.get("base_armor_class")
    if not isinstance(base, int):
        return None
    armor_type = profile.get("armor_type")
    if armor_type == "light":
        return base + dexterity_modifier
    if armor_type == "medium":
        return base + min(2, dexterity_modifier)
    return base
