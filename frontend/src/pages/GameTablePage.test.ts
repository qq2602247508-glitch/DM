import { describe, expect, it } from "vitest";

import { parsePrepDraft } from "../ui/prepDraft";

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
});
