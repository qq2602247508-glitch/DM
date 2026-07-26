import { describe, expect, it } from "vitest";

import type { SearchHit } from "../api/types";
import {
  compendiumMonsterCandidates,
  customMonsterDraft,
  detectArrivalKind,
  monsterDraftFromCandidate,
  parseMonsterActions,
  parseMonsterStats,
  requestedMonsterName,
  suggestedNpcName,
} from "./dynamicEntityDraft";

const hit = {
  score: 0.82,
  chunk: {
    chunk_id: "chunk-1", record_id: "grick", chunk_index: 0,
    text: "穴居攫怪Grick 中型异怪 AC 14 HP 54（12d8） 速度 30尺 力量 10 敏捷 14 体质 11 智力 3 感知 14 魅力 5 CR 2（XP450）",
    name: "穴居攫怪", aliases: ["Grick"], content_type: "monsters", edition: "2025",
    officiality: "official", source_title: "怪物图鉴2025", source_book: "怪物图鉴 2025",
    canonical_url: "https://example.test/grick", source_url: "https://example.test/grick",
    repository_url: null, source_relative_path: null, source_ref: null, source_revision: null,
    source_license: "unknown", heading_path: ["异怪"], section: "穴居攫怪", fragment: null,
    record_checksum: "r", chunk_checksum: "c",
  },
} satisfies SearchHit;

describe("dynamic scene arrivals", () => {
  it("detects monster and NPC arrival language without treating plain mentions as writes", () => {
    expect(detectArrivalKind("这时候来了一个怪物突袭")).toBe("monster");
    expect(detectArrivalKind("这时候出现了多心魔")).toBe("monster");
    expect(detectArrivalKind("突然有个名叫“米拉”的旅人闯入")).toBe("npc");
    expect(detectArrivalKind("附近可能存在怪物")).toBeNull();
    expect(suggestedNpcName("突然有个名叫“米拉”的旅人闯入")).toBe("米拉");
    expect(requestedMonsterName("这时候出现了多心魔")).toBe("多心魔");
  });

  it("extracts usable combat stats and provenance from a real compendium hit", () => {
    expect(parseMonsterStats(hit)).toMatchObject({
      name: "穴居攫怪", armorClass: 14, hp: 54, speed: 30, challengeRating: "2",
      abilityScores: { strength: 10, dexterity: 14, constitution: 11, intelligence: 3, wisdom: 14, charisma: 5 },
    });
    expect(compendiumMonsterCandidates([hit, hit])).toHaveLength(1);
    expect(compendiumMonsterCandidates([hit])[0]?.sourceLabel).toContain("官方");
  });

  it("extracts D&D actions and lets a custom monster bind the matched template", () => {
    const actions = parseMonsterActions(
      "夺心魔 Mind Flayer\n动作\n触须 Tentacles。近战武器攻击：命中 +7，触及 5 尺。命中：15（2d10+4）点心灵伤害。\n心灵震爆 Mind Blast（充能 5~6）。覆盖一处60尺的锥状区域。目标进行一次DC 15的智力豁免，失败受到22（4d8+4）点心灵伤害。",
    );
    expect(actions).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "触须", damage: "2d10+4", range: "5尺", attack_bonus: 7 }),
      expect.objectContaining({ name: "心灵震爆", damage: "4d8+4", range: "60尺锥形", save_dc: 15, save_ability: "intelligence" }),
    ]));

    const mindFlayerHit: SearchHit = {
      ...hit,
      chunk: {
        ...hit.chunk,
        record_id: "mind-flayer",
        chunk_id: "mind-flayer-1",
        name: "夺心魔",
        aliases: ["Mind Flayer", "灵吸怪"],
        text: `夺心魔 AC 15 HP 71 速度 30尺 力量 11 敏捷 12 体质 12 智力 19 感知 17 魅力 17 CR 7\n动作\n${actions.map((action) => action.description).join("\n")}`,
      },
    };
    const candidate = compendiumMonsterCandidates([hit, mindFlayerHit], "出现了多心魔")[0];
    expect(candidate?.label).toBe("夺心魔");
    if (!candidate) throw new Error("expected fuzzy match");
    const officialDraft = monsterDraftFromCandidate(candidate, "出现了多心魔");
    const custom = customMonsterDraft("出现了多心魔", candidate);
    expect(custom).toMatchObject({
      name: "多心魔",
      sourceKey: "custom",
      templateSourceKey: candidate.key,
      armorClass: officialDraft.armorClass,
    });
    expect(custom.actions.length).toBeGreaterThan(0);
  });

  it("parses the official 2025 mind flayer damage and save wording", () => {
    const actions = parseMonsterActions(
      "夺心魔Mind Flayer\n动作Actions\n触须Tentacles。近战攻击检定：+7，触及5尺。命中：22（4d8+4）心灵伤害。\n采脑Extract Brain。体质豁免检定：DC15，单一正受擒于夺心魔触须的生物。失败：55（10d10）穿刺伤害。成功：半伤。\n心灵震爆Mind Blast（充能5–6）。智力豁免检定：DC15，60尺锥形区域内的每名生物。失败：31（6d8+4）心灵伤害。成功：仅半伤。\n施法Spellcasting。",
    );

    expect(actions).toEqual(expect.arrayContaining([
      expect.objectContaining({
        name: "触须",
        damage: "4d8+4",
        attack_bonus: 7,
      }),
      expect.objectContaining({
        name: "采脑",
        damage: "10d10",
        save_dc: 15,
        save_ability: "constitution",
        half_damage_on_save: true,
        auto_eligible: false,
      }),
      expect.objectContaining({
        name: "心灵震爆",
        damage: "6d8+4",
        range: "60尺锥形",
        save_dc: 15,
        save_ability: "intelligence",
        half_damage_on_save: true,
      }),
    ]));
  });
});
