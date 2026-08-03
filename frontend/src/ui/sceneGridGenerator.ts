import type { SceneGrid } from "../api/types";

type CellKind = SceneGrid["cells"][number]["kind"];

export type SceneStructureFamily =
  | "tavern"
  | "sacred_hall"
  | "residence"
  | "warehouse"
  | "workshop"
  | "courtyard"
  | "street"
  | "market_square"
  | "forest_path"
  | "river_crossing"
  | "swamp"
  | "cave"
  | "mine"
  | "dungeon"
  | "crypt"
  | "sewer"
  | "ruins"
  | "tower"
  | "fortress"
  | "dock"
  | "ship"
  | "open_field"
  | "dynamic";

export type SceneStructureDescriptor = {
  family: SceneStructureFamily;
  label: string;
  confidence: "reliable" | "dynamic";
  seed: number;
  water: boolean;
  brokenBridge: boolean;
  vertical: boolean;
  underground: boolean;
};

export type SceneGridAudit = {
  valid: boolean;
  issues: string[];
};

const WIDTH = 18;
const HEIGHT = 12;

function hashText(text: string): number {
  let hash = 2166136261;
  for (const character of text) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

const FAMILY_RULES: Array<[SceneStructureFamily, string, RegExp]> = [
  ["river_crossing", "河流渡口：河道、桥梁与两岸路线", /断桥|桥梁|石桥|木桥|吊桥|渡口|跨河|river crossing|broken bridge|bridge|ford/i],
  ["swamp", "湿地：水洼、泥沼与曲折石堤", /沼泽|湿地|泥沼|泥潭|红树林|swamp|marsh|bog|wetland/i],
  ["sewer", "下水道：主渠、检修道与汇流室", /下水道|排水渠|污水渠|暗渠|sewer|drainage|culvert/i],
  ["crypt", "墓穴：墓室、甬道与祭台", /墓穴|墓室|陵墓|地宫|坟墓|骨室|crypt|tomb|mausoleum|catacomb/i],
  ["mine", "矿井：采掘洞室、矿轨与支撑柱", /矿坑|矿井|矿洞|采石场|mine|quarry|mineshaft/i],
  ["workshop", "工坊：作业区、机械区与储料间", /工坊|作坊|锻造|铁匠|机械|齿轮|磨坊内部|车间|workshop|forge|foundry|mill interior|machinery/i],
  ["warehouse", "仓库：货架巷道、装卸区与库房", /仓库|货栈|粮仓|库房|仓储|warehouse|storehouse|granary|depot/i],
  ["tavern", "酒馆：大厅、吧台与后厨", /酒馆|旅店|客栈|酒吧|餐馆|饭店|tavern|inn|pub/i],
  ["sacred_hall", "圣堂：中殿、耳堂与祭坛", /教堂|神殿|祭坛|圣堂|修道院|礼拜堂|church|temple|chapel|cathedral|shrine/i],
  ["ship", "船只：甲板、桅杆与船舱入口", /海盗船|战船|帆船|船甲板|船舱|舰船|pirate ship|warship|ship deck|vessel/i],
  ["dock", "码头：岸线、栈桥与货运区", /码头|港口|船坞|泊位|栈桥|dock|harbor|harbour|port|pier|wharf/i],
  ["tower", "塔楼：环形楼层、核心区与楼梯", /塔楼|钟楼|瞭望塔|法师塔|高塔|tower|belfry|keep top/i],
  ["fortress", "要塞：城墙、门楼与内防线", /城堡|要塞|堡垒|城寨|城墙|门楼|fortress|castle|citadel|stronghold/i],
  ["courtyard", "院落：开阔中庭、围界与附属建筑", /外院|庭院|院落|中庭|庄园院|磨坊外|courtyard|yard|bailey/i],
  ["market_square", "市集广场：摊位、通路与中心地标", /市集|集市|市场|广场|庙会|market|bazaar|square|plaza/i],
  ["street", "街区：建筑立面、主路与侧巷", /街道|巷道|小巷|城区|城门外|街区|street|alley|avenue|lane/i],
  ["forest_path", "林野：自然边界、林间路径与空地", /森林|林地|树林|丛林|林间|雨林|荒野小径|forest|woods|jungle|woodland/i],
  ["ruins", "遗迹：残墙、坍塌区域与旧中庭", /遗迹|废墟|残垣|古城|神庙废址|ruins|ruined|remains/i],
  ["cave", "洞穴：不规则洞室与天然岩隙", /洞穴|洞窟|岩洞|溶洞|地窖|cave|cavern|grotto|cellar/i],
  ["dungeon", "地牢：牢房、守卫室与连接甬道", /地牢|监牢|牢房|地下城|囚室|dungeon|prison|jail/i],
  ["residence", "宅邸：主厅、侧室与服务通道", /宅邸|住宅|公馆|庄园|宫殿|宴会厅|卧室|客厅|mansion|residence|manor|palace|banquet hall/i],
  ["open_field", "旷野：地形带、掩体与交错路线", /平原|田野|农田|草原|荒漠|沙漠|雪原|旷野|field|plain|desert|steppe|tundra/i],
];

export function describeSceneStructure(
  name: string,
  description: string,
  location = "",
): SceneStructureDescriptor {
  const text = `${name} ${location} ${description}`.trim();
  const matched = FAMILY_RULES.find(([, , pattern]) => pattern.test(text));
  const [family, label] = matched ?? ["dynamic", `动态场地：${name.trim() || "未命名场景"}`];
  return {
    family,
    label,
    confidence: matched ? "reliable" : "dynamic",
    seed: hashText(text),
    water: /河|溪|渠|池|湖|海|潮|水|沼|river|stream|canal|pool|lake|sea|water/i.test(text),
    brokenBridge: /断桥|坍塌.{0,3}桥|损毁.{0,3}桥|broken bridge|collapsed bridge/i.test(text),
    vertical: /楼梯|高台|悬崖|塔|楼层|峭壁|stairs|platform|cliff|tower|level/i.test(text),
    underground: /地下|地底|地窖|洞|墓|矿|下水道|underground|subterranean|cave|crypt|mine|sewer/i.test(text),
  };
}

type GridPainter = ReturnType<typeof createPainter>;

function createPainter() {
  const cells: SceneGrid["cells"] = [];
  const occupied = new Map<string, number>();
  const keyOf = (row: number, col: number) => `${row}:${col}`;
  const add = (row: number, col: number, kind: CellKind, label: string, replace = false, blocksSight = false) => {
    if (row < 1 || row > HEIGHT || col < 1 || col > WIDTH) return;
    const key = keyOf(row, col);
    const index = occupied.get(key);
    if (index !== undefined) {
      if (replace) cells[index] = { row, col, kind, label, blocks_sight: blocksSight };
      return;
    }
    occupied.set(key, cells.length);
    cells.push({ row, col, kind, label, blocks_sight: blocksSight });
  };
  const line = (startRow: number, startCol: number, endRow: number, endCol: number, kind: CellKind, label: string, replace = false) => {
    const rowStep = Math.sign(endRow - startRow);
    const colStep = Math.sign(endCol - startCol);
    let row = startRow;
    let col = startCol;
    while (true) {
      add(row, col, kind, label, replace, kind === "wall");
      if (row === endRow && col === endCol) break;
      if (row !== endRow) row += rowStep;
      if (col !== endCol) col += colStep;
    }
  };
  const rect = (top: number, left: number, bottom: number, right: number, label: string) => {
    line(top, left, top, right, "wall", label);
    line(bottom, left, bottom, right, "wall", label);
    line(top, left, bottom, left, "wall", label);
    line(top, right, bottom, right, "wall", label);
  };
  const fill = (top: number, left: number, bottom: number, right: number, kind: CellKind, label: string) => {
    for (let row = top; row <= bottom; row += 1) {
      for (let col = left; col <= right; col += 1) add(row, col, kind, label);
    }
  };
  const door = (row: number, col: number, label: string) => add(row, col, "door", label, true);
  const spawn = (row: number, col: number, side: "玩家" | "敌方") => add(row, col, "floor", `${side}出生区`, true);
  return { cells, add, line, rect, fill, door, spawn };
}

function buildIndoor(p: GridPainter, d: SceneStructureDescriptor) {
  if (d.family === "tavern") {
    p.line(1, 2, 1, 17, "wall", "酒馆外墙");
    p.line(2, 1, 11, 1, "wall", "酒馆外墙");
    p.line(2, 18, 8, 18, "wall", "酒馆外墙");
    p.line(11, 2, 11, 12, "wall", "酒馆外墙");
    p.line(9, 13, 9, 18, "wall", "后厨外墙");
    p.door(11, 6 + (d.seed % 3), "酒馆正门");
    p.door(9, 15, "后厨侧门");
    p.line(2, 12, 2, 16, "cover", "木制吧台");
    for (const [row, col] of [[4, 4], [4, 8], [7, 4], [7, 8], [6, 12]] as const) p.add(row, col, "cover", "酒桌");
    p.add(4, 17, "object", "壁炉");
  } else if (d.family === "sacred_hall") {
    p.line(1, 6, 1, 13, "wall", "后殿石墙");
    p.line(2, 5, 4, 5, "wall", "后殿石墙");
    p.line(2, 14, 4, 14, "wall", "后殿石墙");
    p.line(5, 2, 5, 5, "wall", "西耳堂石墙");
    p.line(5, 14, 5, 17, "wall", "东耳堂石墙");
    p.line(6, 1, 10, 1, "wall", "中殿外墙");
    p.line(6, 18, 10, 18, "wall", "中殿外墙");
    p.line(11, 2, 11, 17, "wall", "中殿外墙");
    p.door(11, 9, "圣堂正门");
    p.add(2, 9, "object", "主祭坛");
    p.add(2, 10, "object", "主祭坛");
    for (const row of [5, 7, 9]) {
      p.line(row, 5, row, 7, "cover", "长椅");
      p.line(row, 12, row, 14, "cover", "长椅");
    }
  } else if (d.family === "warehouse") {
    p.rect(1, 1, 12, 18, "仓库外墙");
    p.door(12, 7, "装卸大门");
    p.door(12, 8, "装卸大门");
    p.rect(2, 14, 5, 17, "账房隔墙");
    p.door(5, 15, "账房门");
    for (const col of [3, 7, 11]) p.line(3, col, 9, col, "cover", "货架");
    p.line(10, 3, 10, 10, "terrain", "装卸台");
    p.add(7, 15, "object", "起重滑轮");
  } else if (d.family === "workshop") {
    p.rect(1, 2, 11, 17, "工坊外墙");
    p.line(1, 10, 4, 10, "wall", "储料间隔墙");
    p.line(4, 10, 4, 17, "wall", "储料间隔墙");
    p.line(7, 2, 7, 7, "wall", "维修间隔墙");
    p.door(4, 13, "储料间门");
    p.door(7, 5, "维修间门");
    p.door(11, 9, "工坊入口");
    p.line(5, 9, 8, 12, "terrain", "传动机构");
    p.add(6, 11, "cover", "主机械台");
    p.line(3, 3, 3, 7, "cover", "工作台");
  } else {
    p.rect(1, 2, 11, 17, "宅邸外墙");
    p.line(1, 7, 4, 7, "wall", "西侧室隔墙");
    p.line(1, 12, 4, 12, "wall", "东侧室隔墙");
    p.line(8, 2, 8, 6, "wall", "服务区隔墙");
    p.line(8, 13, 8, 17, "wall", "服务区隔墙");
    p.door(11, 9, "宅邸正门");
    p.door(4, 5, "西侧室门");
    p.door(4, 14, "东侧室门");
    p.line(5, 6, 5, 13, "cover", "宴会长桌");
    p.add(2, 9, "object", "主厅壁炉");
    p.line(9, 15, 10, 15, "difficult", "服务通道");
  }
  p.spawn(10, 8, "玩家");
  p.spawn(3, 14, "敌方");
}

function buildCourtyard(p: GridPainter, d: SceneStructureDescriptor) {
  const fortress = d.family === "fortress";
  p.line(1, 1, 1, 18, "wall", fortress ? "城墙" : "北侧围界");
  p.line(1, 1, 12, 1, "wall", fortress ? "城墙" : "西侧围界");
  p.line(1, 18, 12, 18, "wall", fortress ? "城墙" : "东侧围界");
  p.line(12, 1, 12, 7, "wall", fortress ? "门楼" : "南侧围界");
  p.line(12, 12, 12, 18, "wall", fortress ? "门楼" : "南侧围界");
  p.door(12, 8, fortress ? "城门" : "院门");
  p.door(12, 11, fortress ? "城门" : "院门");
  p.rect(2, 3, 5, 8, fortress ? "守卫营房" : "附属建筑");
  p.door(5, 6, "建筑入口");
  p.add(6, 12, "object", fortress ? "旗杆" : "院心水井");
  p.line(8, 4, 8, 7, "cover", fortress ? "拒马" : "木材堆");
  p.line(4, 14, 7, 14, "cover", fortress ? "内防线" : "矮栅栏");
  p.spawn(11, 9, "玩家");
  p.spawn(3, 15, "敌方");
}

function buildUrban(p: GridPainter, d: SceneStructureDescriptor) {
  if (d.family === "dock") {
    p.fill(1, 1, 12, 4, "water", "港湾水面");
    p.line(1, 5, 12, 5, "terrain", "石砌岸线");
    p.line(3, 2, 3, 8, "floor", "北侧栈桥", true);
    p.line(9, 2, 9, 10, "floor", "南侧栈桥", true);
    p.line(2, 12, 2, 17, "cover", "货箱堆");
    p.add(6, 8, "object", "系船柱");
    p.add(7, 14, "cover", "装卸吊机");
  } else if (d.family === "market_square") {
    p.line(1, 1, 1, 18, "wall", "北侧商铺");
    p.line(12, 1, 12, 18, "wall", "南侧商铺");
    for (const [row, col] of [[4, 4], [4, 9], [4, 14], [8, 4], [8, 14]] as const) {
      p.line(row, col, row, col + 2, "cover", "市场摊位");
    }
    p.add(7, 9, "object", "广场中心地标");
    p.door(1, 6, "北侧商铺门");
    p.door(12, 15, "南侧商铺门");
  } else {
    p.line(1, 1, 3, 1, "wall", "西北建筑");
    p.line(1, 2, 1, 18, "wall", "北侧建筑立面");
    p.line(12, 1, 12, 18, "wall", "南侧建筑立面");
    p.line(2, 6, 3, 6, "wall", "店铺隔墙");
    p.line(10, 13, 11, 13, "wall", "住宅隔墙");
    p.door(3, 4, "店铺门");
    p.door(10, 9, "住宅门");
    p.line(5, 7, 5, 10, "cover", "路边摊位");
    p.line(8, 3, 8, 6, "cover", "翻倒货车");
    p.add(7, 15, "object", "路灯");
  }
  p.spawn(10, 7, "玩家");
  p.spawn(3, 15, "敌方");
}

function buildRiverCrossing(p: GridPainter, d: SceneStructureDescriptor) {
  for (let row = 1; row <= HEIGHT; row += 1) {
    const bend = ((row + (d.seed % 3)) % 4 === 0) ? 1 : 0;
    p.line(row, 8 + bend, row, 11 + bend, "water", "连续河道");
  }
  p.line(6, 1, 6, 7, "difficult", "西岸旧路");
  p.line(6, 12, 6, 18, "difficult", "东岸旧路");
  p.line(6, 7, 6, 8, "floor", "西桥头", true);
  p.line(6, 11, 6, 12, "floor", "东桥头", true);
  if (d.brokenBridge) {
    p.add(6, 9, "water", "断桥缺口", true);
    p.add(6, 10, "water", "断桥缺口", true);
  } else {
    p.line(6, 9, 6, 10, "floor", "桥面", true);
  }
  p.line(10, 7, 10, 12, "water", "浅滩替代路线", true);
  p.add(3, 6, "cover", "倒木");
  p.add(9, 14, "cover", "岸边巨石");
  p.spawn(6, 3, "玩家");
  p.spawn(6, 16, "敌方");
}

function buildNatural(p: GridPainter, d: SceneStructureDescriptor) {
  if (d.family === "swamp") {
    for (const [top, left, bottom, right] of [[1, 2, 4, 5], [2, 12, 6, 16], [8, 1, 11, 5], [8, 11, 12, 15]] as const) {
      p.fill(top, left, bottom, right, "water", "沼泽水洼");
    }
    p.line(11, 3, 7, 7, "difficult", "曲折石堤");
    p.line(7, 7, 4, 11, "difficult", "曲折石堤");
    p.line(4, 11, 2, 17, "difficult", "曲折石堤");
    p.add(6, 9, "cover", "枯树根");
  } else if (d.family === "open_field") {
    p.line(2, 1, 4, 6, "difficult", "起伏地形带");
    p.line(9, 12, 11, 18, "difficult", "起伏地形带");
    p.line(6, 5, 6, 14, "cover", "矮墙或田埂");
    p.add(3, 14, "cover", "孤立巨石");
    p.add(9, 5, "object", "废弃营地");
  } else {
    const trees: Array<[number, number]> = [[1, 1], [1, 2], [2, 1], [1, 7], [2, 7], [1, 15], [2, 15], [2, 18], [4, 3], [5, 3], [8, 1], [9, 2], [11, 5], [12, 5], [10, 11], [11, 11], [12, 16], [9, 17], [6, 15]];
    for (const [row, col] of trees) p.add(row, col, "wall", "粗壮树干", false, true);
    p.line(11, 7, 7, 9, "difficult", "林间旧路");
    p.line(7, 9, 2, 16, "difficult", "林间旧路");
    p.line(6, 4, 6, 7, "cover", "倒木");
    if (d.water) p.line(8, 8, 10, 10, "water", "浅溪");
    p.add(4, 12, "cover", "荆棘丛");
  }
  p.spawn(11, 8, "玩家");
  p.spawn(2, 16, "敌方");
}

function buildUnderground(p: GridPainter, d: SceneStructureDescriptor) {
  const top = [4, 3, 2, 2, 1, 1, 2, 1, 2, 2, 1, 2, 2, 3, 3, 4, 5, 5];
  const bottom = [8, 10, 11, 12, 12, 11, 12, 12, 11, 12, 12, 11, 12, 11, 10, 10, 9, 8];
  if (d.family === "cave" || d.family === "mine") {
    for (let col = 1; col <= WIDTH; col += 1) {
      p.add(top[col - 1] ?? 1, col, "wall", d.family === "mine" ? "支护岩壁" : "锯齿岩壁", false, true);
      p.add(bottom[col - 1] ?? HEIGHT, col, "wall", d.family === "mine" ? "支护岩壁" : "锯齿岩壁", false, true);
    }
    p.line(3, 9, 5, 9, "wall", "中央岩脊");
    p.line(7, 9, 10, 9, "wall", "中央岩脊");
    p.door(6, 9, d.family === "mine" ? "矿轨隧道" : "狭窄岩隙");
    p.add(5, 4, "cover", d.family === "mine" ? "矿车" : "巨型石笋");
    p.add(8, 14, "object", d.family === "mine" ? "采掘面" : "地下水池");
  } else if (d.family === "sewer") {
    p.line(1, 5, 12, 5, "wall", "西侧检修道墙");
    p.line(1, 14, 12, 14, "wall", "东侧检修道墙");
    p.fill(1, 8, 12, 11, "water", "连续污水主渠");
    p.line(4, 5, 4, 14, "floor", "检修桥", true);
    p.line(9, 5, 9, 14, "floor", "汇流室桥面", true);
    p.door(7, 5, "西侧闸门");
    p.add(6, 16, "object", "控制阀");
  } else {
    const crypt = d.family === "crypt";
    p.rect(1, 1, 5, 7, crypt ? "西墓室石墙" : "西侧牢房墙");
    p.rect(1, 12, 5, 18, crypt ? "东墓室石墙" : "东侧牢房墙");
    p.rect(7, 3, 12, 16, crypt ? "主墓室石墙" : "守卫室石墙");
    p.door(3, 7, crypt ? "西墓室门" : "西牢门");
    p.door(3, 12, crypt ? "东墓室门" : "东牢门");
    p.door(7, 9, crypt ? "主墓室门" : "守卫室门");
    p.add(9, 10, "object", crypt ? "石棺祭台" : "狱卒桌");
    p.line(4, 8, 4, 11, "difficult", crypt ? "骨堆甬道" : "中央甬道");
  }
  p.spawn(10, 6, "玩家");
  p.spawn(3, 15, "敌方");
}

function buildSpecial(p: GridPainter, d: SceneStructureDescriptor) {
  if (d.family === "ship") {
    p.line(1, 6, 1, 13, "wall", "船艏围栏");
    p.line(2, 4, 10, 2, "wall", "左舷");
    p.line(2, 15, 10, 17, "wall", "右舷");
    p.line(11, 5, 11, 14, "wall", "船艉围栏");
    p.add(5, 9, "cover", "主桅杆", false, true);
    p.add(8, 6, "object", "船舱入口");
    p.line(3, 13, 5, 13, "cover", "索具与木箱");
    p.spawn(9, 9, "玩家");
    p.spawn(2, 10, "敌方");
  } else if (d.family === "tower") {
    const ring: Array<[number, number]> = [[2, 6], [1, 7], [1, 12], [2, 13], [3, 15], [5, 16], [9, 16], [11, 13], [12, 12], [12, 7], [11, 6], [10, 4], [4, 4]];
    for (let index = 0; index < ring.length; index += 1) {
      const [row, col] = ring[index]!;
      const next = ring[(index + 1) % ring.length]!;
      p.line(row, col, next[0], next[1], "wall", "塔楼环形外墙");
    }
    p.add(6, 10, "terrain", "中心竖井");
    p.add(8, 12, "object", "螺旋楼梯");
    p.line(4, 7, 4, 12, "cover", "弧形书架");
    p.door(11, 9, "塔楼入口");
    p.spawn(10, 9, "玩家");
    p.spawn(3, 10, "敌方");
  } else {
    p.line(2, 3, 2, 8, "wall", "残破北墙");
    p.line(2, 12, 5, 12, "wall", "残破殿墙");
    p.line(8, 2, 11, 2, "wall", "坍塌西墙");
    p.line(11, 2, 11, 7, "wall", "坍塌西墙");
    p.line(9, 13, 9, 18, "wall", "残存回廊");
    p.add(6, 9, "object", "旧中庭遗迹");
    p.line(4, 4, 5, 6, "difficult", "碎石坍塌区");
    p.line(8, 10, 10, 12, "cover", "断裂石柱");
    p.spawn(10, 5, "玩家");
    p.spawn(3, 15, "敌方");
  }
}

function buildDynamic(p: GridPainter, d: SceneStructureDescriptor, sceneName: string) {
  const zoneCount = 2 + (d.seed % 4);
  const natural = d.water || /林|野|谷|月|风|云|沙|雪|garden|wild|valley/i.test(sceneName);
  for (let index = 0; index < zoneCount; index += 1) {
    const left = 2 + ((d.seed >>> (index * 3)) % 12);
    const top = 1 + ((d.seed >>> (index * 4 + 2)) % 8);
    const width = 3 + ((d.seed >>> (index + 5)) % 3);
    const height = 2 + ((d.seed >>> (index + 8)) % 3);
    if (natural) {
      p.line(top, left, Math.min(HEIGHT, top + height), Math.min(WIDTH, left + width), index % 2 ? "difficult" : "cover", `${sceneName}·地貌区${index + 1}`);
    } else {
      p.rect(top, left, Math.min(HEIGHT, top + height), Math.min(WIDTH, left + width), `${sceneName}·功能区${index + 1}`);
      p.door(Math.min(HEIGHT, top + height), Math.min(WIDTH, left + 1), `${sceneName}·连接口${index + 1}`);
    }
  }
  const pathRow = 4 + (d.seed % 5);
  p.line(pathRow, 1, pathRow, 18, "difficult", `${sceneName}·主连接路径`, true);
  p.add(2 + (d.seed % 7), 8 + (d.seed % 4), "object", `${sceneName}·核心特征`, true);
  p.spawn(pathRow, 2, "玩家");
  p.spawn(pathRow, 17, "敌方");
}

function buildGrid(descriptor: SceneStructureDescriptor, sceneName: string): SceneGrid {
  const p = createPainter();
  switch (descriptor.family) {
    case "tavern": case "sacred_hall": case "residence": case "warehouse": case "workshop":
      buildIndoor(p, descriptor); break;
    case "courtyard": case "fortress":
      buildCourtyard(p, descriptor); break;
    case "street": case "market_square": case "dock":
      buildUrban(p, descriptor); break;
    case "river_crossing":
      buildRiverCrossing(p, descriptor); break;
    case "forest_path": case "swamp": case "open_field":
      buildNatural(p, descriptor); break;
    case "cave": case "mine": case "dungeon": case "crypt": case "sewer":
      buildUnderground(p, descriptor); break;
    case "ruins": case "tower": case "ship":
      buildSpecial(p, descriptor); break;
    default:
      buildDynamic(p, descriptor, sceneName.trim() || "未知场地");
  }
  return {
    width: WIDTH,
    height: HEIGHT,
    cell_size_ft: 5,
    theme: `${descriptor.label} · ${descriptor.confidence === "dynamic" ? "动态语义结构" : "可靠结构预设"}`,
    cells: p.cells,
  };
}

export function auditSceneGrid(grid: SceneGrid, descriptor?: SceneStructureDescriptor): SceneGridAudit {
  const issues: string[] = [];
  const coordinates = new Set<string>();
  for (const cell of grid.cells) {
    const key = `${cell.row}:${cell.col}`;
    if (cell.row < 1 || cell.row > grid.height || cell.col < 1 || cell.col > grid.width) issues.push(`坐标越界：${key}`);
    if (coordinates.has(key)) issues.push(`坐标重复：${key}`);
    coordinates.add(key);
  }
  for (const side of ["玩家", "敌方"] as const) {
    const spawns = grid.cells.filter((cell) => cell.kind === "floor" && cell.label === `${side}出生区`);
    if (spawns.length !== 1) issues.push(`${side}出生区数量应为 1，实际为 ${spawns.length}`);
  }
  if (descriptor?.family === "river_crossing") {
    for (let row = 1; row <= grid.height; row += 1) {
      if (!grid.cells.some((cell) => cell.row === row && cell.kind === "water" && /河道|断桥|浅滩/.test(cell.label))) issues.push(`河道在第 ${row} 行不连续`);
    }
    if (!grid.cells.some((cell) => /桥头|桥面|断桥缺口/.test(cell.label))) issues.push("桥梁场景缺少跨水结构");
  }
  if (descriptor?.family === "swamp" && !grid.cells.some((cell) => cell.kind === "water")) issues.push("湿地场景缺少水域");
  if (descriptor?.family === "courtyard" && !grid.cells.some((cell) => /院心|院门/.test(cell.label))) issues.push("院落缺少中心开阔区或入口");
  if (descriptor?.confidence === "dynamic" && !grid.theme.includes("动态语义结构")) issues.push("未知语义未标记为动态结构");
  return { valid: issues.length === 0, issues };
}

/** Generates a deterministic tactical grid from scene, location and description semantics. */
export function generateTacticalSceneGrid(name: string, description: string, location = ""): SceneGrid {
  const descriptor = describeSceneStructure(name, description, location);
  return buildGrid(descriptor, name);
}

export function findSceneSpawnCells(grid: SceneGrid, side: "player" | "enemy"): { row: number; col: number }[] {
  const marker = side === "player" ? "玩家出生区" : "敌方出生区";
  return grid.cells.filter((cell) => cell.kind === "floor" && cell.label === marker).map(({ row, col }) => ({ row, col }));
}
