import { describe, expect, it } from "vitest";

import { buildFallbackPrepDraft, parsePrepDraft } from "../ui/prepDraft";

describe("parsePrepDraft", () => {
  it("parses strict prep sections into importable atoms", () => {
    const atoms = parsePrepDraft(`
## 场景
- 旧教堂｜被异端信徒占领
## NPC
- 老牧师｜表面友善，实际拖延时间
## 怪物
- 异端信徒｜潜伏在地下室
## 任务
- 调查失踪商队｜找到商队去向
## 线索
- 祭坛钥匙｜可以打开地下暗门
## 物品
- 银制圣徽｜价值 25 金币
`);
    expect(atoms.map((atom) => [atom.kind, atom.name])).toEqual([
      ["scene", "旧教堂"],
      ["npc", "老牧师"],
      ["monster", "异端信徒"],
      ["quest", "调查失踪商队"],
      ["clue", "祭坛钥匙"],
      ["item", "银制圣徽"],
    ]);
  });

  it("does not import bullets under DM advice as the previous atom kind", () => {
    const atoms = parsePrepDraft(`
## 物品
- 银制圣徽｜价值 25 金币
## DM建议
- 让守卫先以言语拖延玩家
- 具体检定由 DM 从规则库确认
`);
    expect(atoms.map((atom) => [atom.kind, atom.name])).toEqual([
      ["item", "银制圣徽"],
    ]);
  });

  it("parses chapter-aware scene outlines", () => {
    const atoms = parsePrepDraft(`
## 场景
- 第一章｜1｜深水城集结｜让玩家彼此认识｜酒馆开场｜共同接受委托｜线人失踪｜决定追查｜前往旧教堂
`);
    expect(atoms[0]).toMatchObject({
      kind: "scene",
      name: "深水城集结",
      sceneOutline: {
        chapterTitle: "第一章",
        sceneOrder: 1,
        opening: "酒馆开场",
        transition: "前往旧教堂",
      },
    });
  });

  it("turns a one-line tavern brief into locations, scenes and a D&D encounter", () => {
    const text = buildFallbackPrepDraft(
      "玩家1级，新手村，一个博德之门的小酒馆集结，然后遇到地精发生战斗",
    );
    const atoms = parsePrepDraft(text);
    expect(atoms.some((atom) => atom.kind === "location" && atom.name.includes("酒馆"))).toBe(true);
    expect(atoms.filter((atom) => atom.kind === "scene")).toHaveLength(2);
    expect(atoms.some((atom) => atom.kind === "monster" && atom.name === "地精")).toBe(true);
    expect(text).not.toContain("混入非 D&D");
  });
});
