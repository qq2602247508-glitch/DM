from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PaletteName = Literal[
    "ocean",
    "ember",
    "ice",
    "ashen",
    "moss",
    "violet",
    "toxic",
    "crystal",
    "brass",
    "sandstone",
    "fungal",
    "shadow",
    "radiant",
    "forest",
    "storm",
]


class ThemeDescriptor(BaseModel):
    """A visual/semantic contract. Mechanical values are deliberately forbidden."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    theme_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,47}$")
    label: str = Field(min_length=2, max_length=40)
    palette: PaletteName
    source_kind: Literal["preset", "compiled"]
    confidence: float = Field(ge=0, le=1)
    keywords: tuple[str, ...] = Field(min_length=1, max_length=8)
    atmosphere: str = Field(min_length=2, max_length=100)
    wall_label: str = Field(min_length=1, max_length=24)
    floor_label: str = Field(min_length=1, max_length=24)
    cover_label: str = Field(min_length=1, max_length=24)
    door_label: str = Field(min_length=1, max_length=24)
    room_functions: tuple[str, ...] = Field(min_length=6, max_length=12)
    environment_objects: tuple[str, ...] = Field(min_length=3, max_length=8)
    hazard_motifs: tuple[str, ...] = Field(min_length=1, max_length=6)
    monster_queries: tuple[str, ...] = Field(min_length=1, max_length=8)
    npc_roles: tuple[str, ...] = Field(min_length=1, max_length=6)
    loot_queries: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator(
        "label", "atmosphere", "wall_label", "floor_label", "cover_label", "door_label"
    )
    @classmethod
    def reject_mechanics(cls, value: str) -> str:
        if re.search(r"\b(?:AC|CR|HP|XP|DC)\b|\d+d\d+|\d+环|伤害骰", value, re.IGNORECASE):
            raise ValueError("theme descriptors cannot contain mechanical values")
        return value


class _Family(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    aliases: tuple[str, ...]
    descriptor: ThemeDescriptor


def _descriptor(
    theme_id: str,
    label: str,
    palette: PaletteName,
    aliases: tuple[str, ...],
    *,
    atmosphere: str,
    wall: str,
    floor: str,
    cover: str,
    door: str,
    rooms: tuple[str, ...],
    objects: tuple[str, ...],
    hazards: tuple[str, ...],
    monsters: tuple[str, ...],
    npcs: tuple[str, ...],
    loot: tuple[str, ...],
) -> _Family:
    return _Family(
        aliases=aliases,
        descriptor=ThemeDescriptor(
            theme_id=theme_id,
            label=label,
            palette=palette,
            source_kind="preset",
            confidence=0.96,
            keywords=aliases[:8],
            atmosphere=atmosphere,
            wall_label=wall,
            floor_label=floor,
            cover_label=cover,
            door_label=door,
            room_functions=rooms,
            environment_objects=objects,
            hazard_motifs=hazards,
            monster_queries=monsters,
            npc_roles=npcs,
            loot_queries=loot,
        ),
    )


THEME_FAMILIES = (
    _descriptor(
        "sahuagin",
        "鲨华鱼人 / 深海",
        "ocean",
        ("鲨华", "渔人", "鱼人", "深海", "海底", "潮汐", "sahuagin"),
        atmosphere="咸湿潮气、涨落水位与深海祭祀痕迹",
        wall="潮湿岩壁",
        floor="积水石地",
        cover="珊瑚柱",
        door="贝壳潮门",
        rooms=(
            "潮门入口",
            "积水哨室",
            "断船厅",
            "贝壳祭坛",
            "盐渍牢房",
            "育卵池",
            "珊瑚藏宝室",
            "潮汐仪式厅",
            "鲨华男爵巢穴",
        ),
        objects=("珊瑚柱", "沉船残骸", "育卵池", "潮汐闸门"),
        hazards=("涨潮", "暗流", "湿滑地面"),
        monsters=("鲨华鱼人", "海洋", "水生", "鲨鱼"),
        npcs=("被放逐的鲨华向导", "被囚禁的沿海水手"),
        loot=("水下", "海洋", "珍珠", "三叉戟", "潮汐", "珊瑚"),
    ),
    _descriptor(
        "ocean",
        "海洋遗迹",
        "ocean",
        ("海洋", "海岸", "沉船", "岛屿", "海水", "水下", "ocean"),
        atmosphere="海水侵蚀、沉船残骸与变化的潮位",
        wall="盐蚀岩壁",
        floor="积水石地",
        cover="沉船残骸",
        door="防水舱门",
        rooms=(
            "潮水入口",
            "沉船前厅",
            "压舱室",
            "水下回廊",
            "船员舱",
            "礁石洞",
            "货舱宝库",
            "航海仪式厅",
            "深水核心",
        ),
        objects=("沉船残骸", "礁石", "锚链", "破损舵轮"),
        hazards=("涨潮", "暗流", "溺水区域"),
        monsters=("海洋", "水生", "鲨鱼", "海怪"),
        npcs=("遇难水手", "海岸向导"),
        loot=("水下", "航海", "珍珠", "海洋"),
    ),
    _descriptor(
        "goblin",
        "地精巢穴",
        "moss",
        ("地精", "大地精", "熊地精", "goblin"),
        atmosphere="粗糙工事、低矮通道与层层伏击陷阱",
        wall="加固洞壁",
        floor="泥土地面",
        cover="木板路障",
        door="拼装木门",
        rooms=(
            "隐蔽入口",
            "警戒哨室",
            "伏击廊道",
            "狼栏",
            "杂物工坊",
            "俘虏牢房",
            "劫掠品仓库",
            "战鼓大厅",
            "首领巢穴",
        ),
        objects=("木板路障", "捕兽夹", "狼笼", "战鼓"),
        hazards=("绊索", "落石", "伏击孔"),
        monsters=("地精", "大地精", "熊地精", "座狼"),
        npcs=("地精叛逃者", "被俘的商旅"),
        loot=("陷阱", "工具", "劫掠品", "弹药"),
    ),
    _descriptor(
        "forest",
        "远古森林",
        "forest",
        ("森林", "深林", "林地", "树海", "古树", "丛林", "forest"),
        atmosphere="浓密树冠、盘根路径与活跃的自然灵性",
        wall="纠缠树墙",
        floor="落叶地面",
        cover="盘根古树",
        door="藤蔓拱门",
        rooms=(
            "林缘入口",
            "猎径前厅",
            "盘根回廊",
            "兽穴",
            "德鲁伊营地",
            "古树空洞",
            "自然宝库",
            "月光林间地",
            "森林之心",
        ),
        objects=("盘根古树", "倒木", "荆棘丛", "图腾石"),
        hazards=("纠缠藤蔓", "毒刺植物", "迷途花粉"),
        monsters=("野兽", "植物", "精类", "森林"),
        npcs=("林地向导", "隐居德鲁伊"),
        loot=("自然", "植物", "德鲁伊", "狩猎"),
    ),
    _descriptor(
        "swamp",
        "剧毒沼泽",
        "toxic",
        ("沼泽", "湿地", "毒沼", "沉没神庙", "泥潭", "毒雾", "swamp"),
        atmosphere="腐水、毒雾与半沉没遗迹交织",
        wall="苔藓残墙",
        floor="泥泞浅水",
        cover="盘根古木",
        door="藤蔓石门",
        rooms=(
            "芦苇入口",
            "沉没前厅",
            "孢子温室",
            "毒雾回廊",
            "蜥蜴人哨所",
            "腐水祭坛",
            "盘根密室",
            "泥潭宝库",
            "沉没圣所",
        ),
        objects=("毒蘑菇", "盘根古木", "半沉石像", "腐水池", "孢子囊"),
        hazards=("毒雾", "流沙泥潭", "孢子爆发"),
        monsters=("蜥蜴人", "植物", "真菌", "毒", "沼泽"),
        npcs=("湿地向导", "被困的采药人", "蜥蜴人叛逃者"),
        loot=("毒素", "解毒剂", "植物", "自然", "沼泽"),
    ),
    _descriptor(
        "crystal",
        "奥术水晶矿洞",
        "crystal",
        ("水晶", "晶体", "紫水晶", "矿晶", "晶簇", "共鸣", "crystal"),
        atmosphere="晶体折光、奥术嗡鸣与不稳定共振",
        wall="晶脉岩壁",
        floor="碎晶地面",
        cover="共鸣晶簇",
        door="晶格闸门",
        rooms=(
            "碎晶入口",
            "矿车转运厅",
            "共鸣廊道",
            "晶簇生长室",
            "奥术勘探站",
            "折光迷室",
            "晶核宝库",
            "谐振仪式厅",
            "巨型晶洞",
        ),
        objects=("共鸣晶簇", "矿车", "聚焦棱镜", "奥术测量仪"),
        hazards=("晶体爆裂", "奥术回响", "折光幻象"),
        monsters=("水晶", "构装", "元素", "奥术", "矿洞"),
        npcs=("奥术矿物学家", "失踪的矿工", "晶体研究员"),
        loot=("水晶", "奥术", "棱镜", "宝石", "法器"),
    ),
    _descriptor(
        "clockwork",
        "机械钟楼",
        "brass",
        ("机械", "钟楼", "齿轮", "发条", "蒸汽", "黄铜", "clockwork"),
        atmosphere="齿轮咬合、蒸汽泄压与周期性钟鸣",
        wall="铆钉金属壁",
        floor="黄铜踏板",
        cover="巨型齿轮",
        door="齿轮闸门",
        rooms=(
            "校时入口",
            "配重井",
            "齿轮机房",
            "蒸汽阀室",
            "钟摆长廊",
            "自动机工坊",
            "零件库",
            "主发条室",
            "钟鸣控制厅",
        ),
        objects=("巨型齿轮", "蒸汽管道", "钟摆", "维修台", "配重块"),
        hazards=("蒸汽喷射", "齿轮碾压", "定时机关"),
        monsters=("构装体", "自动机", "机械", "魔像"),
        npcs=("矮人工匠", "失控的维修傀儡", "钟楼看守"),
        loot=("机械", "工具", "黄铜", "发条", "构装"),
    ),
    _descriptor(
        "fungal",
        "幽光菌林",
        "fungal",
        ("蕈人相关怪物", "蕈人", "蘑菇", "菌菇", "孢子", "真菌", "菌林", "myconid"),
        atmosphere="幽光菌伞、飘散孢子与潮湿菌毯",
        wall="菌丝洞壁",
        floor="柔软菌毯",
        cover="巨型菌伞",
        door="菌丝膜门",
        rooms=(
            "孢子入口",
            "菌伞林",
            "菌丝走廊",
            "培育池",
            "腐殖洞",
            "幽光孢室",
            "药菌储藏室",
            "菌环祭场",
            "母菌核心",
        ),
        objects=("巨型菌伞", "孢子囊", "菌丝网", "发光苔藓"),
        hazards=("致幻孢子", "毒菌云", "黏性菌丝"),
        monsters=("真菌", "蕈人", "植物", "孢子"),
        npcs=("蕈人向导", "孢子学者", "受感染的探险者"),
        loot=("真菌", "药剂", "孢子", "植物", "解毒"),
    ),
    _descriptor(
        "fire",
        "火山与熔岩",
        "ember",
        ("火山", "岩浆", "熔炉", "烈焰", "炎热", "inferno"),
        atmosphere="灼热气浪、熔岩裂隙与硫磺烟尘",
        wall="焦黑岩壁",
        floor="熔渣地面",
        cover="黑曜石柱",
        door="熔铸石门",
        rooms=(
            "焦岩入口",
            "熔渣哨站",
            "岩浆断桥",
            "火焰祭坛",
            "冷却石牢",
            "硫磺洞",
            "黑曜石宝库",
            "熔炉仪式厅",
            "炎兽巢穴",
        ),
        objects=("黑曜石柱", "岩浆沟", "熔炉", "冷却阀"),
        hazards=("熔岩喷溅", "高温烟气", "崩裂地面"),
        monsters=("火焰", "火元素", "岩浆", "炼狱"),
        npcs=("耐热锻造师", "被困的矿工"),
        loot=("火焰", "耐热", "黑曜石", "锻造"),
    ),
    _descriptor(
        "frost",
        "冰窟与霜寒",
        "ice",
        ("冰窟", "冰川", "霜寒", "冻原", "寒冰", "frost"),
        atmosphere="刺骨寒风、蓝冰裂隙与霜纹反光",
        wall="蓝冰壁",
        floor="覆霜地面",
        cover="寒晶柱",
        door="冰封石门",
        rooms=(
            "覆霜入口",
            "冰墙哨室",
            "裂隙冰桥",
            "霜纹祭坛",
            "冻牢",
            "蓝冰洞",
            "寒晶宝库",
            "极光仪式厅",
            "霜兽巢穴",
        ),
        objects=("寒晶柱", "冰桥", "冻结水池", "雪堆"),
        hazards=("薄冰", "极寒", "冰锥坠落"),
        monsters=("寒冷", "冰霜", "冬狼", "雪人"),
        npcs=("冻原猎人", "失温的探险者"),
        loot=("寒冷", "冰霜", "保暖", "寒晶"),
    ),
    _descriptor(
        "undead",
        "亡灵墓穴",
        "ashen",
        ("亡灵", "墓穴", "骷髅", "坟墓", "陵寝", "undead"),
        atmosphere="积尘墓道、幽冷死气与破损葬仪",
        wall="墓砖壁",
        floor="积灰石地",
        cover="石棺",
        door="墓室石门",
        rooms=(
            "墓道入口",
            "守墓厅",
            "骨瓮廊",
            "陪葬室",
            "停灵厅",
            "幽魂回廊",
            "殉葬宝库",
            "死灵祭室",
            "主墓室",
        ),
        objects=("石棺", "骨瓮", "墓碑", "长明灯"),
        hazards=("死气侵蚀", "坍塌墓道", "诅咒封印"),
        monsters=("亡灵", "骷髅", "僵尸", "幽魂"),
        npcs=("守墓人", "未安息的证人"),
        loot=("亡灵", "死灵", "圣水", "护符", "墓葬"),
    ),
    _descriptor(
        "aberration",
        "异怪污染",
        "violet",
        ("夺心魔", "异怪", "心灵", "触须", "畸变", "mind flayer"),
        atmosphere="扭曲几何、心灵低语与有机污染",
        wall="脉动肉壁",
        floor="黏液地面",
        cover="神经柱",
        door="虹膜门",
        rooms=(
            "污染入口",
            "感知节点",
            "实验囚室",
            "脑池回廊",
            "畸变培育室",
            "心灵共鸣厅",
            "样本库",
            "意识仪式室",
            "主脑节点",
        ),
        objects=("神经柱", "脑池", "培养舱", "心灵导管"),
        hazards=("心灵冲击", "黏液污染", "空间扭曲"),
        monsters=("异怪", "夺心魔", "心灵", "畸变"),
        npcs=("逃脱的实验体", "失忆的研究者"),
        loot=("心灵", "异界", "触须", "星界"),
    ),
    _descriptor(
        "cult",
        "秘教仪式",
        "violet",
        ("邪教", "秘教", "献祭", "异端", "仪式", "cult"),
        atmosphere="遮蔽烛火、禁忌符号与秘密集会痕迹",
        wall="刻符石壁",
        floor="仪式地面",
        cover="祭仪立柱",
        door="符印暗门",
        rooms=(
            "伪装入口",
            "信徒宿舍",
            "献祭准备室",
            "亵渎祭坛",
            "囚禁室",
            "经卷库",
            "圣物密藏",
            "召唤仪式厅",
            "教首密室",
        ),
        objects=("祭仪立柱", "经卷架", "烛台", "献祭台"),
        hazards=("召唤反噬", "符文陷阱", "群体恐惧"),
        monsters=("邪教徒", "狂信徒", "召唤生物"),
        npcs=("动摇的信徒", "被囚禁的证人"),
        loot=("仪式", "圣徽", "诅咒", "经卷"),
    ),
    _descriptor(
        "desert",
        "沙海遗迹",
        "sandstone",
        ("沙漠", "沙海", "荒漠", "金字塔", "流沙", "desert"),
        atmosphere="风蚀砂岩、干燥热浪与掩埋遗迹",
        wall="风蚀砂岩壁",
        floor="积沙石地",
        cover="残破方尖碑",
        door="砂岩封门",
        rooms=(
            "风沙入口",
            "朝圣前厅",
            "流沙回廊",
            "蓄水室",
            "木乃伊准备室",
            "星象厅",
            "贡品宝库",
            "太阳祭室",
            "王室墓厅",
        ),
        objects=("方尖碑", "陶罐", "石像", "蓄水池"),
        hazards=("流沙", "热浪", "落砂机关"),
        monsters=("沙漠", "木乃伊", "蝎", "蛇"),
        npcs=("沙漠向导", "遗迹学者"),
        loot=("沙漠", "太阳", "宝石", "古代"),
    ),
    _descriptor(
        "shadow",
        "暗影虚空",
        "shadow",
        ("暗影", "虚空", "阴影", "幽暗", "梦魇", "shadow"),
        atmosphere="吞光阴影、错位回声与不稳定边界",
        wall="暗影幕墙",
        floor="黯淡石地",
        cover="虚空裂柱",
        door="影幕门",
        rooms=(
            "暮色入口",
            "无光廊道",
            "回声厅",
            "影像牢笼",
            "失落记忆室",
            "虚空裂隙",
            "暗影宝库",
            "梦魇仪式厅",
            "无光核心",
        ),
        objects=("虚空裂柱", "影幕", "黑镜", "熄灭灯台"),
        hazards=("吞光区域", "空间错位", "梦魇幻象"),
        monsters=("暗影", "幽魂", "虚空", "潜伏怪"),
        npcs=("迷失的旅者", "暗影研究者"),
        loot=("暗影", "隐形", "黑暗", "位移"),
    ),
    _descriptor(
        "radiant",
        "圣光遗迹",
        "radiant",
        ("圣光", "神圣", "天界", "太阳", "圣殿", "celestial"),
        atmosphere="金色光束、肃穆圣像与残留祝福",
        wall="洁白圣墙",
        floor="镶金石地",
        cover="圣像柱",
        door="日轮圣门",
        rooms=(
            "朝圣入口",
            "净化前厅",
            "唱诗回廊",
            "圣物室",
            "忏悔室",
            "日轮大厅",
            "祝福宝库",
            "神谕祭坛",
            "至圣所",
        ),
        objects=("圣像柱", "日轮镜", "祈祷长椅", "圣水池"),
        hazards=("炫目圣光", "审判符文", "失衡祝福"),
        monsters=("天界", "神圣守卫", "构装体"),
        npcs=("朝圣者", "圣殿守护者"),
        loot=("神圣", "治疗", "光明", "圣徽"),
    ),
    _descriptor(
        "storm",
        "风暴要塞",
        "storm",
        ("风暴", "雷霆", "闪电", "暴雨", "天空", "storm"),
        atmosphere="雷鸣回荡、强风通道与持续电弧",
        wall="雷击石壁",
        floor="导电金属地面",
        cover="避雷柱",
        door="风压闸门",
        rooms=(
            "迎风入口",
            "避雷前厅",
            "风洞廊道",
            "蓄能室",
            "观测台",
            "雷鸣大厅",
            "电容宝库",
            "风暴祭坛",
            "天穹核心",
        ),
        objects=("避雷柱", "风轮", "蓄能线圈", "观测仪"),
        hazards=("强风", "雷击", "导电积水"),
        monsters=("风元素", "雷电", "飞行", "风暴"),
        npcs=("气象术士", "失事飞行员"),
        loot=("雷电", "飞行", "风暴", "抗性"),
    ),
)


_STOP_TERMS = (
    "一个",
    "一座",
    "这个",
    "地下城",
    "地牢",
    "建筑",
    "场景",
    "生成",
    "里面",
    "风格",
    "相关",
    "充满",
)
_CUSTOM_PALETTES: tuple[PaletteName, ...] = (
    "crystal",
    "brass",
    "fungal",
    "shadow",
    "radiant",
    "storm",
    "toxic",
    "sandstone",
    "moss",
    "violet",
)


def _extract_terms(text: str) -> tuple[str, ...]:
    chunks = re.findall(r"[\u4e00-\u9fff]{2,16}|[a-z][a-z0-9 -]{2,24}", text.lower())
    terms: list[str] = []
    for chunk in chunks:
        value = chunk.strip()
        for stop in _STOP_TERMS:
            value = value.replace(stop, "")
        if len(value) > 10:
            value = value[:10]
        if len(value) >= 2 and value not in terms:
            terms.append(value)
    return tuple(terms[:6]) or ("未知主题",)


def compile_theme(text: str) -> ThemeDescriptor:
    lowered = text.lower()
    ranked = [
        (sum(1 for alias in family.aliases if alias.lower() in lowered), index, family)
        for index, family in enumerate(THEME_FAMILIES)
    ]
    score, _, family = max(ranked, key=lambda item: (item[0], -item[1]))
    if score:
        matched = tuple(alias for alias in family.aliases if alias.lower() in lowered)
        return family.descriptor.model_copy(
            update={
                "keywords": matched[:8] or family.descriptor.keywords,
                "confidence": min(1.0, 0.84 + score * 0.06),
            }
        )
    terms = _extract_terms(text)
    digest = hashlib.sha256(text.strip().lower().encode()).hexdigest()
    palette = _CUSTOM_PALETTES[int(digest[:8], 16) % len(_CUSTOM_PALETTES)]
    subject = terms[0]
    return ThemeDescriptor(
        theme_id=f"custom-{digest[:10]}",
        label=f"动态主题 · {subject}",
        palette=palette,
        source_kind="compiled",
        confidence=0.62,
        keywords=terms,
        atmosphere=f"围绕“{subject}”组织的独特环境线索与空间叙事",
        wall_label=f"{subject}边界",
        floor_label="主题地面",
        cover_label=f"{subject}掩体",
        door_label=f"{subject}门扉",
        room_functions=(
            f"{subject}入口",
            f"{subject}前厅",
            f"{subject}回廊",
            f"{subject}工坊",
            f"{subject}观测室",
            f"{subject}密室",
            f"{subject}宝库",
            f"{subject}仪式厅",
            f"{subject}核心",
        ),
        environment_objects=(f"{subject}立柱", f"{subject}装置", f"{subject}残迹"),
        hazard_motifs=(f"{subject}环境异变",),
        monster_queries=terms,
        npc_roles=(f"熟悉{subject}的向导", f"受{subject}影响的幸存者"),
        loot_queries=terms,
    )
