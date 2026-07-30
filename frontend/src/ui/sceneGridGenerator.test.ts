import { describe, expect, it } from "vitest";

import {
  auditSceneGrid,
  describeSceneStructure,
  findSceneSpawnCells,
  generateTacticalSceneGrid,
  type SceneStructureFamily,
} from "./sceneGridGenerator";

describe("generateTacticalSceneGrid", () => {
  it("is deterministic and uses location text as semantic input", () => {
    const first = generateTacticalSceneGrid("突然袭击", "敌人从门外冲入", "银鹿旅店酒馆");
    const second = generateTacticalSceneGrid("突然袭击", "敌人从门外冲入", "银鹿旅店酒馆");
    expect(first).toEqual(second);
    expect(first.theme).toContain("酒馆");
    expect(first.cells.some((cell) => cell.label === "木制吧台")).toBe(true);
  });

  it.each<[string, string, SceneStructureFamily, RegExp]>([
    ["雨林中的断桥", "湍急溪流切断旧路", "river_crossing", /断桥缺口/],
    ["磨坊外院", "水渠旁有木栅栏和磨坊建筑", "courtyard", /院心水井|附属建筑/],
    ["地下机械工坊", "齿轮主轴和维修间", "workshop", /主机械台|传动机构/],
    ["贵族宅邸宴会厅", "仆役从服务通道进入", "residence", /宴会长桌/],
    ["废弃仓库", "装卸区堆满木箱", "warehouse", /货架|装卸台/],
    ["古代墓穴", "石棺后的甬道通往骨室", "crypt", /石棺祭台/],
    ["城市下水道", "主渠在汇流室交汇", "sewer", /连续污水主渠/],
    ["港口码头", "栈桥伸向潮水", "dock", /港湾水面|栈桥/],
    ["海盗船甲板", "桅杆和索具遮挡视线", "ship", /主桅杆/],
    ["法师塔顶层", "螺旋楼梯围绕中心竖井", "tower", /中心竖井/],
    ["城堡庭院", "门楼内布置拒马", "fortress", /城门|拒马/],
    ["沼泽石堤", "泥沼间只有曲折小路", "swamp", /曲折石堤/],
    ["沙漠遗迹", "残墙和坍塌石柱散落", "ruins", /残破|坍塌/],
    ["幽暗矿井", "矿车沿轨道进入采掘面", "mine", /矿车|采掘面/],
    ["王城大市集", "摊位围绕广场中心", "market_square", /市场摊位|广场中心/],
    ["迷雾森林", "林间旧路穿过树林", "forest_path", /林间旧路|倒木/],
  ])("creates a distinct semantic structure for %s", (name, description, family, feature) => {
    const descriptor = describeSceneStructure(name, description);
    const grid = generateTacticalSceneGrid(name, description);
    expect(descriptor.family).toBe(family);
    expect(descriptor.confidence).toBe("reliable");
    expect(grid.cells.some((cell) => feature.test(cell.label))).toBe(true);
    expect(findSceneSpawnCells(grid, "player")).toHaveLength(1);
    expect(findSceneSpawnCells(grid, "enemy")).toHaveLength(1);
    expect(auditSceneGrid(grid, descriptor)).toEqual({ valid: true, issues: [] });
  });

  it("models a broken bridge as a continuous river with a real gap", () => {
    const descriptor = describeSceneStructure("雨林断桥", "河水冲毁中央桥面");
    const grid = generateTacticalSceneGrid("雨林断桥", "河水冲毁中央桥面");
    expect(descriptor).toMatchObject({ family: "river_crossing", brokenBridge: true, water: true });
    expect(grid.cells.filter((cell) => cell.label === "断桥缺口" && cell.kind === "water")).toHaveLength(2);
    for (let row = 1; row <= grid.height; row += 1) {
      expect(grid.cells.some((cell) => cell.row === row && cell.kind === "water")).toBe(true);
    }
  });

  it("uses a stable dynamic structure for unknown semantics instead of the old four-room fallback", () => {
    const descriptor = describeSceneStructure("纸月回声庭", "折叠的白色回声沿弧线移动");
    const first = generateTacticalSceneGrid("纸月回声庭", "折叠的白色回声沿弧线移动");
    const second = generateTacticalSceneGrid("纸月回声庭", "折叠的白色回声沿弧线移动");
    const another = generateTacticalSceneGrid("玻璃鲸脊", "蓝色鸣响从背脊扩散");
    expect(descriptor).toMatchObject({ family: "dynamic", confidence: "dynamic" });
    expect(first).toEqual(second);
    expect(first).not.toEqual(another);
    expect(first.theme).toContain("动态语义结构");
    expect(first.cells.some((cell) => cell.label.includes("纸月回声庭·核心特征"))).toBe(true);
    expect(first.cells.some((cell) => cell.label === "西北侧室石墙")).toBe(false);
    expect(auditSceneGrid(first, descriptor)).toEqual({ valid: true, issues: [] });
  });

  it("keeps coordinates, cell kinds and spawn cells compatible with SceneGrid", () => {
    const allowedKinds = new Set([
      "floor", "wall", "cover", "door", "object", "water", "difficult", "terrain",
      "light", "trap", "treasure", "furniture", "portal",
    ]);
    const samples = [
      generateTacticalSceneGrid("荒野哨站", "平原上的战斗"),
      generateTacticalSceneGrid("地下城牢房", "守卫室连接三间囚室"),
      generateTacticalSceneGrid("钟楼", "顶层有螺旋楼梯"),
    ];
    for (const grid of samples) {
      expect(grid).toMatchObject({ width: 18, height: 12, cell_size_ft: 5 });
      expect(grid.cells.every((cell) => (
        allowedKinds.has(cell.kind)
        && cell.row >= 1 && cell.row <= grid.height
        && cell.col >= 1 && cell.col <= grid.width
      ))).toBe(true);
      expect(new Set(grid.cells.map((cell) => `${cell.row}:${cell.col}`)).size).toBe(grid.cells.length);
      expect(auditSceneGrid(grid).valid).toBe(true);
    }
  });
});
