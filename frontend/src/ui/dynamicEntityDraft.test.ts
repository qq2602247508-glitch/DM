import { describe, expect, it } from "vitest";

import type { SearchHit } from "../api/types";
import {
  compendiumMonsterCandidates,
  detectArrivalKind,
  parseMonsterStats,
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
    expect(detectArrivalKind("突然有个名叫“米拉”的旅人闯入")).toBe("npc");
    expect(detectArrivalKind("附近可能存在怪物")).toBeNull();
    expect(suggestedNpcName("突然有个名叫“米拉”的旅人闯入")).toBe("米拉");
  });

  it("extracts usable combat stats and provenance from a real compendium hit", () => {
    expect(parseMonsterStats(hit)).toMatchObject({
      name: "穴居攫怪", armorClass: 14, hp: 54, speed: 30, challengeRating: "2",
      abilityScores: { strength: 10, dexterity: 14, constitution: 11, intelligence: 3, wisdom: 14, charisma: 5 },
    });
    expect(compendiumMonsterCandidates([hit, hit])).toHaveLength(1);
    expect(compendiumMonsterCandidates([hit])[0]?.sourceLabel).toContain("官方");
  });
});
