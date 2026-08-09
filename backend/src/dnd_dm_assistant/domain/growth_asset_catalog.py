from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

WEAPON_SOURCE_RECORD_ID = "0f155fdb630249957251a76e"
MASTERY_SOURCE_RECORD_ID = "08fd9f442907e6520302fddf"
METAMAGIC_SOURCE_RECORD_ID = "9abaecf07ccb5165a00b80ec"


@dataclass(frozen=True, slots=True)
class WeaponAsset:
    id: str
    name: str
    english_name: str
    category: str
    range_kind: str
    damage: str
    properties: str
    mastery: str
    source_record_id: str = WEAPON_SOURCE_RECORD_ID
    rule_year: str = "2024"

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "asset_kind": "weapon",
            "mastery_source_record_id": MASTERY_SOURCE_RECORD_ID,
            "selected_asset_status": "full",
            "mastery_effect_status": "separate_asset_contract",
        }


@dataclass(frozen=True, slots=True)
class MetamagicAsset:
    id: str
    name: str
    english_name: str
    sorcery_point_cost: int
    source_record_id: str = METAMAGIC_SOURCE_RECORD_ID
    rule_year: str = "2024"

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "asset_kind": "metamagic_option",
            "selected_asset_status": "full",
            "effect_status": "separate_asset_contract",
        }


def _weapon(
    slug: str,
    name: str,
    english_name: str,
    category: str,
    range_kind: str,
    damage: str,
    properties: str,
    mastery: str,
) -> WeaponAsset:
    return WeaponAsset(
        id=f"weapon:{slug}",
        name=name,
        english_name=english_name,
        category=category,
        range_kind=range_kind,
        damage=damage,
        properties=properties,
        mastery=mastery,
    )


# Player's Handbook 2024, Weapons table.  This deliberately models the
# selected weapon as an asset and leaves each mastery property's attack effect
# to its own runtime contract.
WEAPON_ASSETS: tuple[WeaponAsset, ...] = (
    _weapon("club", "短棒", "Club", "simple", "melee", "1d4 bludgeoning", "light", "缓速"),
    _weapon(
        "dagger",
        "匕首",
        "Dagger",
        "simple",
        "melee",
        "1d4 piercing",
        "finesse, light, thrown 20/60",
        "迅击",
    ),
    _weapon(
        "greatclub", "巨棒", "Greatclub", "simple", "melee", "1d8 bludgeoning", "two-handed", "推离"
    ),
    _weapon(
        "handaxe",
        "手斧",
        "Handaxe",
        "simple",
        "melee",
        "1d6 slashing",
        "light, thrown 20/60",
        "侵扰",
    ),
    _weapon(
        "javelin", "标枪", "Javelin", "simple", "melee", "1d6 piercing", "thrown 30/120", "缓速"
    ),
    _weapon(
        "light-hammer",
        "轻锤",
        "Light Hammer",
        "simple",
        "melee",
        "1d4 bludgeoning",
        "light, thrown 20/60",
        "迅击",
    ),
    _weapon("mace", "硬头锤", "Mace", "simple", "melee", "1d6 bludgeoning", "", "削弱"),
    _weapon(
        "quarterstaff",
        "长棍",
        "Quarterstaff",
        "simple",
        "melee",
        "1d6 bludgeoning",
        "versatile 1d8",
        "失衡",
    ),
    _weapon("sickle", "镰刀", "Sickle", "simple", "melee", "1d4 slashing", "light", "迅击"),
    _weapon(
        "spear",
        "矛",
        "Spear",
        "simple",
        "melee",
        "1d6 piercing",
        "thrown 20/60, versatile 1d8",
        "削弱",
    ),
    _weapon(
        "dart", "飞镖", "Dart", "simple", "ranged", "1d4 piercing", "finesse, thrown 20/60", "侵扰"
    ),
    _weapon(
        "light-crossbow",
        "轻弩",
        "Light Crossbow",
        "simple",
        "ranged",
        "1d8 piercing",
        "ammunition 80/320, loading, two-handed",
        "缓速",
    ),
    _weapon(
        "shortbow",
        "短弓",
        "Shortbow",
        "simple",
        "ranged",
        "1d6 piercing",
        "ammunition 80/320, two-handed",
        "侵扰",
    ),
    _weapon(
        "sling",
        "投石索",
        "Sling",
        "simple",
        "ranged",
        "1d4 bludgeoning",
        "ammunition 30/120",
        "缓速",
    ),
    _weapon(
        "battleaxe",
        "战斧",
        "Battleaxe",
        "martial",
        "melee",
        "1d8 slashing",
        "versatile 1d10",
        "失衡",
    ),
    _weapon("flail", "链枷", "Flail", "martial", "melee", "1d8 bludgeoning", "", "削弱"),
    _weapon(
        "glaive",
        "长柄刀",
        "Glaive",
        "martial",
        "melee",
        "1d10 slashing",
        "heavy, reach, two-handed",
        "擦掠",
    ),
    _weapon(
        "greataxe",
        "巨斧",
        "Greataxe",
        "martial",
        "melee",
        "1d12 slashing",
        "heavy, two-handed",
        "横扫",
    ),
    _weapon(
        "greatsword",
        "巨剑",
        "Greatsword",
        "martial",
        "melee",
        "2d6 slashing",
        "heavy, two-handed",
        "擦掠",
    ),
    _weapon(
        "halberd",
        "戟",
        "Halberd",
        "martial",
        "melee",
        "1d10 slashing",
        "heavy, reach, two-handed",
        "横扫",
    ),
    _weapon(
        "lance",
        "骑枪",
        "Lance",
        "martial",
        "melee",
        "1d10 piercing",
        "heavy, reach, two-handed",
        "失衡",
    ),
    _weapon(
        "longsword",
        "长剑",
        "Longsword",
        "martial",
        "melee",
        "1d8 slashing",
        "versatile 1d10",
        "削弱",
    ),
    _weapon(
        "maul", "巨锤", "Maul", "martial", "melee", "2d6 bludgeoning", "heavy, two-handed", "失衡"
    ),
    _weapon("morningstar", "钉头锤", "Morningstar", "martial", "melee", "1d8 piercing", "", "削弱"),
    _weapon(
        "pike",
        "长矛",
        "Pike",
        "martial",
        "melee",
        "1d10 piercing",
        "heavy, reach, two-handed",
        "推离",
    ),
    _weapon("rapier", "刺剑", "Rapier", "martial", "melee", "1d8 piercing", "finesse", "侵扰"),
    _weapon(
        "scimitar", "弯刀", "Scimitar", "martial", "melee", "1d6 slashing", "finesse, light", "迅击"
    ),
    _weapon(
        "shortsword",
        "短剑",
        "Shortsword",
        "martial",
        "melee",
        "1d6 piercing",
        "finesse, light",
        "侵扰",
    ),
    _weapon(
        "trident",
        "三叉戟",
        "Trident",
        "martial",
        "melee",
        "1d8 piercing",
        "thrown 20/60, versatile 1d10",
        "失衡",
    ),
    _weapon(
        "warpick", "战镐", "Warpick", "martial", "melee", "1d8 piercing", "versatile 1d10", "削弱"
    ),
    _weapon(
        "warhammer",
        "战锤",
        "Warhammer",
        "martial",
        "melee",
        "1d8 bludgeoning",
        "versatile 1d10",
        "推离",
    ),
    _weapon("whip", "鞭", "Whip", "martial", "melee", "1d4 slashing", "finesse, reach", "缓速"),
    _weapon(
        "blowgun",
        "吹箭筒",
        "Blowgun",
        "martial",
        "ranged",
        "1 piercing",
        "ammunition 25/100, loading",
        "侵扰",
    ),
    _weapon(
        "hand-crossbow",
        "手弩",
        "Hand Crossbow",
        "martial",
        "ranged",
        "1d6 piercing",
        "ammunition 30/120, light, loading",
        "侵扰",
    ),
    _weapon(
        "heavy-crossbow",
        "重弩",
        "Heavy Crossbow",
        "martial",
        "ranged",
        "1d10 piercing",
        "ammunition 100/400, heavy, loading, two-handed",
        "推离",
    ),
    _weapon(
        "longbow",
        "长弓",
        "Longbow",
        "martial",
        "ranged",
        "1d8 piercing",
        "ammunition 150/600, heavy, two-handed",
        "缓速",
    ),
    _weapon(
        "musket",
        "火铳",
        "Musket",
        "martial",
        "ranged",
        "1d12 piercing",
        "ammunition 40/120, loading, two-handed",
        "缓速",
    ),
    _weapon(
        "pistol",
        "手铳",
        "Pistol",
        "martial",
        "ranged",
        "1d10 piercing",
        "ammunition 30/90, loading",
        "侵扰",
    ),
)


METAMAGIC_ASSETS: tuple[MetamagicAsset, ...] = (
    MetamagicAsset("metamagic:careful-spell", "谨慎法术", "Careful Spell", 1),
    MetamagicAsset("metamagic:distant-spell", "远程法术", "Distant Spell", 1),
    MetamagicAsset("metamagic:empowered-spell", "强效法术", "Empowered Spell", 1),
    MetamagicAsset("metamagic:extended-spell", "延效法术", "Extended Spell", 1),
    MetamagicAsset("metamagic:heightened-spell", "升阶法术", "Heightened Spell", 2),
    MetamagicAsset("metamagic:quickened-spell", "瞬发法术", "Quickened Spell", 2),
    MetamagicAsset("metamagic:seeking-spell", "追踪法术", "Seeking Spell", 1),
    MetamagicAsset("metamagic:subtle-spell", "精妙法术", "Subtle Spell", 1),
    MetamagicAsset("metamagic:transmuted-spell", "转化法术", "Transmuted Spell", 1),
    MetamagicAsset("metamagic:twinned-spell", "孪生法术", "Twinned Spell", 1),
)


def _asset_lookup(assets: tuple[Any, ...], value: object) -> Any | None:
    identity = str(value or "").strip().casefold()
    for asset in assets:
        if identity in {asset.id.casefold(), asset.name.casefold(), asset.english_name.casefold()}:
            return asset
    return None


def weapon_asset(value: object) -> WeaponAsset | None:
    return _asset_lookup(WEAPON_ASSETS, value)


def metamagic_asset(value: object) -> MetamagicAsset | None:
    return _asset_lookup(METAMAGIC_ASSETS, value)


def weapon_is_eligible(
    asset: WeaponAsset,
    *,
    policy: str,
    proficiencies: tuple[object, ...] | list[object],
) -> bool:
    if policy == "simple_or_martial":
        return asset.category in {"simple", "martial"}
    if policy == "simple_or_martial_melee":
        return asset.category in {"simple", "martial"} and asset.range_kind == "melee"
    if policy != "character_proficient":
        return False
    labels = {
        str(item).strip().casefold()
        for item in proficiencies
        if isinstance(item, str) and str(item).strip()
    }
    if asset.name.casefold() in labels or asset.english_name.casefold() in labels:
        return True
    category_labels = (
        {"简易武器", "simple weapons", "simple weapon"}
        if asset.category == "simple"
        else {"军用武器", "martial weapons", "martial weapon"}
    )
    return bool(labels & category_labels)
