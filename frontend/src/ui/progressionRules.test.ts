import { describe, expect, it } from "vitest";

import {
  encounterDifficulty,
  levelFromXp,
  nextLevelXp,
  shiftDifficulty,
  xpForChallengeRating,
} from "./progressionRules";

describe("progression rules", () => {
  it("uses the D&D experience thresholds", () => {
    expect(nextLevelXp(1)).toBe(300);
    expect(levelFromXp(899)).toBe(2);
    expect(levelFromXp(900)).toBe(3);
    expect(nextLevelXp(20)).toBeNull();
  });

  it("maps challenge ratings to experience", () => {
    expect(xpForChallengeRating("1/4")).toBe(50);
    expect(xpForChallengeRating("5")).toBe(1_800);
    expect(xpForChallengeRating("unknown")).toBe(0);
  });

  it("applies bounded narrative difficulty shifts", () => {
    const base = encounterDifficulty([3, 3, 3, 3], 2_800);
    expect(shiftDifficulty(base, -1)).not.toBe("high");
    expect(shiftDifficulty("trivial", -10)).toBe("trivial");
    expect(shiftDifficulty("high", 10)).toBe("high");
  });

  it("matches the 2024 DMG per-character encounter budget examples", () => {
    expect(encounterDifficulty([1, 1, 1, 1], 200)).toBe("low");
    expect(encounterDifficulty([3, 3, 3, 3, 3], 1_125)).toBe("moderate");
    expect(encounterDifficulty([15, 15, 15, 15, 15, 15], 46_800)).toBe("high");
  });
});
