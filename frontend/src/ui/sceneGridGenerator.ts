import type { SceneGrid } from "../api/types";

type CellKind = SceneGrid["cells"][number]["kind"];
type GridTheme = "tavern" | "church" | "cave" | "forest" | "street" | "generic";

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

function classifyTheme(text: string): GridTheme {
  if (/酒馆|旅店|客栈|酒吧|餐馆|饭店|tavern|inn|pub/i.test(text)) return "tavern";
  if (/教堂|神殿|祭坛|圣堂|修道院|神祇|church|temple|chapel|cathedral/i.test(text)) return "church";
  if (/洞穴|洞窟|地窖|矿坑|地下|暗室|岩洞|cave|cavern|mine|underground/i.test(text)) return "cave";
  if (/森林|林地|树林|丛林|荒野|沼泽|forest|woods|jungle|swamp/i.test(text)) return "forest";
  if (/街道|巷道|小巷|市集|广场|城区|城门|street|alley|market|square/i.test(text)) return "street";
  return "generic";
}

function buildGrid(theme: GridTheme, seed: number): SceneGrid {
  const cells: SceneGrid["cells"] = [];
  const occupied = new Map<string, number>();
  const keyOf = (row: number, col: number) => `${row}:${col}`;
  const add = (
    row: number,
    col: number,
    kind: CellKind,
    label: string,
    replace = false,
    blocksSight = false,
  ) => {
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
  const line = (
    startRow: number,
    startCol: number,
    endRow: number,
    endCol: number,
    kind: CellKind,
    label: string,
  ) => {
    const rowStep = Math.sign(endRow - startRow);
    const colStep = Math.sign(endCol - startCol);
    let row = startRow;
    let col = startCol;
    while (true) {
      add(row, col, kind, label);
      if (row === endRow && col === endCol) break;
      if (row !== endRow) row += rowStep;
      if (col !== endCol) col += colStep;
    }
  };
  const door = (row: number, col: number, label: string) => add(row, col, "door", label, true);
  const spawn = (row: number, col: number, side: "玩家" | "敌方") => {
    add(row, col, "floor", `${side}出生区`);
  };

  if (theme === "tavern") {
    // L-shaped public room with a narrower kitchen/storage wing.
    line(1, 2, 1, 17, "wall", "酒馆外墙");
    line(2, 1, 10, 1, "wall", "酒馆外墙");
    line(2, 18, 8, 18, "wall", "酒馆外墙");
    line(11, 2, 11, 12, "wall", "酒馆外墙");
    line(9, 13, 9, 17, "wall", "后厨外墙");
    line(10, 12, 10, 12, "wall", "转角墙");
    line(2, 1, 2, 1, "wall", "酒馆外墙");
    line(10, 1, 10, 1, "wall", "酒馆外墙");
    line(1, 17, 1, 17, "wall", "酒馆外墙");
    door(11, 6 + (seed % 3), "酒馆正门");
    door(9, 15, "后厨侧门");
    line(2, 12, 2, 16, "cover", "木制吧台");
    add(2, 17, "object", "酒桶架");
    add(3, 16, "object", "吧台活板门");
    for (const [row, col] of [[4, 4], [4, 8], [7, 4], [7, 8], [6, 12]] as const) {
      add(row, col, "cover", "酒桌");
      add(row, col - 1, "object", "木椅");
      add(row, col + 1, "object", "木椅");
    }
    add(4, 17, "object", "壁炉");
    add(7, 15, "cover", "翻倒的酒桶");
    add(8, 17, "object", "通往二楼的楼梯");
    spawn(9, 5, "玩家");
    spawn(3, 14, "敌方");
  } else if (theme === "church") {
    // Stepped transepts give the church a cruciform, visibly non-rectangular outline.
    line(1, 6, 1, 13, "wall", "后殿石墙");
    line(2, 5, 4, 5, "wall", "后殿石墙");
    line(2, 14, 4, 14, "wall", "后殿石墙");
    line(5, 2, 5, 5, "wall", "耳堂石墙");
    line(5, 14, 5, 17, "wall", "耳堂石墙");
    line(6, 1, 10, 1, "wall", "礼拜堂外墙");
    line(6, 18, 10, 18, "wall", "礼拜堂外墙");
    line(11, 2, 11, 17, "wall", "礼拜堂外墙");
    line(6, 2, 6, 2, "wall", "礼拜堂外墙");
    line(6, 17, 6, 17, "wall", "礼拜堂外墙");
    door(11, 9, "教堂正门");
    door(5, 3, "西侧门");
    add(2, 9, "object", "主祭坛");
    add(2, 10, "object", "主祭坛");
    add(3, 7, "object", "圣像");
    add(3, 12, "object", "圣器柜");
    for (const row of [5, 7, 9]) {
      line(row, 5, row, 7, "cover", "长椅");
      line(row, 12, row, 14, "cover", "长椅");
    }
    add(6, 3, "cover", "倒塌石柱", false, true);
    add(6, 16, "object", "告解室");
    spawn(10, 9, "玩家");
    spawn(3, 9, "敌方");
  } else if (theme === "cave") {
    // Jagged boundary and two chambers linked by a narrow natural passage.
    const top = [4, 3, 2, 2, 1, 1, 2, 1, 2, 2, 1, 2, 2, 3, 3, 4, 5, 5];
    const bottom = [8, 10, 11, 12, 12, 11, 12, 12, 11, 12, 12, 11, 12, 11, 10, 10, 9, 8];
    for (let col = 1; col <= WIDTH; col += 1) {
      add(top[col - 1] ?? 1, col, "wall", "锯齿岩壁");
      add(bottom[col - 1] ?? HEIGHT, col, "wall", "锯齿岩壁");
    }
    line(5, 1, 8, 1, "wall", "洞穴岩壁");
    line(6, 18, 8, 18, "wall", "洞穴岩壁");
    line(3, 9, 5, 9, "wall", "中央岩脊");
    line(7, 9, 10, 9, "wall", "中央岩脊");
    door(6, 9, "狭窄岩隙");
    door(7, 18, "洞穴入口");
    add(5, 4, "cover", "巨型石笋", false, true);
    add(8, 6, "cover", "坍塌岩块");
    add(4, 13, "cover", "天然岩柱", false, true);
    add(8, 14, "object", "地下水池");
    add(6, 16, "object", "发光菌丛");
    add(9, 11, "cover", "断裂矿车");
    spawn(7, 16, "玩家");
    spawn(6, 4, "敌方");
  } else if (theme === "forest") {
    // Open woodland: tree clusters shape lanes instead of a box-shaped room.
    const treeCells: [number, number][] = [
      [1, 1], [1, 2], [2, 1], [1, 6], [2, 6], [1, 12], [1, 13], [2, 13],
      [1, 18], [2, 18], [4, 3], [5, 3], [4, 4], [8, 1], [9, 1], [10, 2],
      [11, 5], [12, 5], [12, 6], [10, 10], [11, 10], [12, 10], [8, 16],
      [8, 17], [9, 17], [11, 14], [12, 14], [12, 15], [11, 18], [12, 18],
    ];
    for (const [row, col] of treeCells) add(row, col, "wall", "粗壮树干");
    line(6, 5, 6, 8, "cover", "倒木");
    line(3, 14, 5, 14, "cover", "荆棘丛");
    add(8, 7, "object", "浅溪");
    add(8, 8, "object", "浅溪");
    add(9, 9, "object", "浅溪");
    add(5, 11, "cover", "苔石");
    add(9, 13, "cover", "猎人废弃营火");
    add(3, 8, "object", "林间高地");
    add(12, 8, "door", "南侧林间小径");
    add(1, 16, "door", "北侧林间小径");
    spawn(11, 8, "玩家");
    spawn(3, 16, "敌方");
  } else if (theme === "street") {
    // Building fronts border a broad street; alleys and doors break the frontage.
    line(1, 1, 3, 1, "wall", "西侧建筑");
    line(1, 2, 1, 18, "wall", "北侧建筑");
    line(2, 5, 3, 5, "wall", "北侧店铺隔墙");
    line(2, 12, 3, 12, "wall", "北侧店铺隔墙");
    line(12, 1, 12, 18, "wall", "南侧建筑");
    line(10, 6, 11, 6, "wall", "南侧店铺隔墙");
    line(10, 14, 11, 14, "wall", "南侧店铺隔墙");
    door(3, 3, "铁匠铺门");
    door(3, 9, "商店门");
    door(10, 11, "住宅门");
    door(12, 16, "后巷入口");
    line(5, 7, 5, 9, "cover", "市场摊位");
    line(8, 3, 8, 5, "cover", "翻倒货车");
    add(6, 14, "cover", "水井");
    add(8, 16, "object", "路灯");
    add(4, 3, "object", "木箱堆");
    add(9, 10, "cover", "石制路障");
    spawn(6, 2, "玩家");
    spawn(7, 17, "敌方");
  } else {
    // Four independently enclosed rooms open into a cross-shaped central hall.
    // Everything outside the room/corridor footprint becomes an unwalkable
    // dark void, which makes the result read like a real dungeon floor plan.
    const rect = (
      top: number,
      left: number,
      bottom: number,
      right: number,
      label: string,
    ) => {
      line(top, left, top, right, "wall", label);
      line(bottom, left, bottom, right, "wall", label);
      line(top, left, bottom, left, "wall", label);
      line(top, right, bottom, right, "wall", label);
    };
    rect(1, 1, 5, 7, "西北侧室石墙");
    rect(1, 12, 5, 18, "东北侧室石墙");
    rect(7, 1, 12, 7, "西南储藏室石墙");
    rect(7, 12, 12, 18, "东南密室石墙");
    line(2, 7, 2, 12, "wall", "北走廊墙");
    line(4, 7, 4, 7, "wall", "中央走廊墙");
    line(4, 12, 4, 12, "wall", "中央走廊墙");
    line(3, 7, 10, 7, "wall", "中央走廊西墙");
    line(3, 12, 10, 12, "wall", "中央走廊东墙");
    line(10, 7, 10, 12, "wall", "中央大厅南墙");

    door(3, 7, "西北侧室门");
    door(3, 12, "东北侧室门");
    door(9, 7, "西南储藏室门");
    door(9, 12, "东南密室门");
    door(10, 9 + (seed % 2), "地城主要入口");

    add(3, 4, "floor", "西北侧室");
    add(3, 15, "floor", "东北侧室");
    add(3, 9, "floor", "北侧走廊");
    add(6, 9, "floor", "中央大厅");
    add(11, 9, "floor", "入口前厅");
    add(9, 4, "floor", "西南储藏室");
    add(9, 15, "floor", "东南密室");
    add(2, 3, "cover", "坍塌书架", false, true);
    add(2, 15, "object", "机关石碑");
    add(6, 8, "cover", "断裂石柱", false, true);
    add(7, 11, "cover", "倒塌拱门", false, true);
    add(8, 3, "object", "可搜索木箱");
    add(8, 16, "cover", "碎石掩体");
    spawn(8, 9, "玩家");
    spawn(3, 15, "敌方");

    const insideFootprint = (row: number, col: number) => (
      (row >= 1 && row <= 5 && col >= 1 && col <= 7)
      || (row >= 1 && row <= 5 && col >= 12 && col <= 18)
      || (row >= 7 && row <= 12 && col >= 1 && col <= 7)
      || (row >= 7 && row <= 12 && col >= 12 && col <= 18)
      || (row >= 2 && row <= 10 && col >= 7 && col <= 12)
      || (row === 11 && col >= 9 && col <= 10)
    );
    for (let row = 1; row <= HEIGHT; row += 1) {
      for (let col = 1; col <= WIDTH; col += 1) {
        if (!insideFootprint(row, col)) add(row, col, "wall", "地图外区域");
      }
    }
  }

  const themeNames: Record<GridTheme, string> = {
    tavern: "酒馆：大厅、吧台与后厨",
    church: "教堂：中殿、耳堂与祭坛",
    cave: "洞穴：双洞室与狭窄岩隙",
    forest: "森林：林间空地与天然掩体",
    street: "街道：店铺立面、市场与侧巷",
    generic: "多房间不规则战斗区域",
  };
  return { width: WIDTH, height: HEIGHT, cell_size_ft: 5, theme: themeNames[theme], cells };
}

/**
 * Generates a deterministic tactical grid from the scene and its parent
 * location. Existing callers can continue passing only name and description.
 */
export function generateTacticalSceneGrid(
  name: string,
  description: string,
  location = "",
): SceneGrid {
  const text = `${name} ${location} ${description}`.trim();
  const theme = classifyTheme(text);
  return buildGrid(theme, hashText(text));
}

export function findSceneSpawnCells(
  grid: SceneGrid,
  side: "player" | "enemy",
): { row: number; col: number }[] {
  const marker = side === "player" ? "玩家出生区" : "敌方出生区";
  return grid.cells
    .filter((cell) => cell.kind === "floor" && cell.label === marker)
    .map(({ row, col }) => ({ row, col }));
}
