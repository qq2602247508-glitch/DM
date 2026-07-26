import type { SceneGrid } from "../api/types";

function hashText(text: string): number {
  let hash = 2166136261;
  for (const character of text) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function generateTacticalSceneGrid(name: string, description: string): SceneGrid {
  const text = `${name} ${description}`;
  const seed = hashText(text);
  const church = /教堂|神殿|祭坛|圣堂|神祇/.test(text);
  const cave = /洞穴|地窖|矿坑|地下|暗室/.test(text);
  const width = 18;
  const height = 12;
  const cells: SceneGrid["cells"] = [];
  const occupied = new Set<string>();
  const add = (row: number, col: number, kind: SceneGrid["cells"][number]["kind"], label: string) => {
    if (row < 1 || row > height || col < 1 || col > width) return;
    const key = `${row}:${col}`;
    if (occupied.has(key)) return;
    occupied.add(key);
    cells.push({ row, col, kind, label });
  };

  for (let col = 1; col <= width; col += 1) {
    add(1, col, "wall", cave ? "岩壁" : "外墙");
    add(height, col, "wall", cave ? "岩壁" : "外墙");
  }
  for (let row = 2; row < height; row += 1) {
    add(row, 1, "wall", cave ? "岩壁" : "外墙");
    add(row, width, "wall", cave ? "岩壁" : "外墙");
  }

  // Offset chambers and corridors make the playable floor non-rectangular
  // while keeping a deterministic path through the whole map.
  const verticalWall = 7 + (seed % 3);
  const verticalDoor = 4 + (seed % 5);
  for (let row = 2; row <= 8; row += 1) {
    if (row !== verticalDoor) add(row, verticalWall, "wall", cave ? "岩柱" : "隔墙");
  }
  const horizontalWall = 7 + (seed % 2);
  const horizontalDoor = 11 + (seed % 4);
  for (let col = verticalWall; col < width; col += 1) {
    if (col !== horizontalDoor) add(horizontalWall, col, "wall", cave ? "塌方边界" : "侧室墙");
  }
  add(verticalDoor, verticalWall, "door", "内门");
  add(horizontalWall, horizontalDoor, "door", cave ? "狭窄洞口" : "侧门");
  add(height, 4 + (seed % 10), "door", "主要入口");

  if (church) {
    add(3, 13, "object", "祭坛");
    add(3, 14, "object", "祭坛");
    for (const row of [5, 7, 9]) {
      add(row, 11, "cover", "长椅");
      add(row, 15, "cover", "长椅");
    }
    add(5, 4, "object", "圣像");
    add(9, 5, "cover", "倒塌石柱");
  } else if (cave) {
    add(3, 4, "cover", "石笋");
    add(5, 12, "cover", "岩柱");
    add(9, 14, "object", "地下水池");
    add(10, 6, "cover", "塌落岩块");
  } else {
    add(3, 4, "cover", "大型掩体");
    add(5, 13, "cover", "翻倒家具");
    add(9, 4, "object", "可互动物");
    add(10, 14, "cover", "碎石障碍");
  }

  return {
    width,
    height,
    cell_size_ft: 5,
    theme: church ? "复杂旧教堂" : cave ? "不规则地下区域" : "多房间战斗区域",
    cells,
  };
}
