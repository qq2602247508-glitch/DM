export const XP_THRESHOLDS = [
  0, 300, 900, 2_700, 6_500, 14_000, 23_000, 34_000, 48_000, 64_000,
  85_000, 100_000, 120_000, 140_000, 165_000, 195_000, 225_000, 265_000,
  305_000, 355_000,
] as const;

const CR_XP: Record<string, number> = {
  "0": 10, "1/8": 25, "1/4": 50, "1/2": 100,
  "1": 200, "2": 450, "3": 700, "4": 1_100, "5": 1_800,
  "6": 2_300, "7": 2_900, "8": 3_900, "9": 5_000, "10": 5_900,
  "11": 7_200, "12": 8_400, "13": 10_000, "14": 11_500, "15": 13_000,
  "16": 15_000, "17": 18_000, "18": 20_000, "19": 22_000, "20": 25_000,
  "21": 33_000, "22": 41_000, "23": 50_000, "24": 62_000,
  "25": 75_000, "26": 90_000, "27": 105_000, "28": 120_000,
  "29": 135_000, "30": 155_000,
};

const ENCOUNTER_BUDGET_2024: Record<number, [low: number, moderate: number, high: number]> = {
  1: [50, 75, 100], 2: [100, 150, 200], 3: [150, 225, 400],
  4: [250, 375, 500], 5: [500, 750, 1_100], 6: [600, 1_000, 1_400],
  7: [750, 1_300, 1_700], 8: [1_000, 1_700, 2_100],
  9: [1_300, 2_000, 2_600], 10: [1_600, 2_300, 3_100],
  11: [1_900, 2_900, 4_100], 12: [2_200, 3_700, 4_700],
  13: [2_600, 4_200, 5_400], 14: [2_900, 4_900, 6_200],
  15: [3_300, 5_400, 7_800], 16: [3_800, 6_100, 9_800],
  17: [4_500, 7_200, 11_700], 18: [5_000, 8_700, 14_200],
  19: [5_500, 10_700, 17_200], 20: [6_400, 13_200, 22_000],
};

export type Difficulty = "trivial" | "low" | "moderate" | "high";

export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  trivial: "微不足道",
  low: "低",
  moderate: "中等",
  high: "高",
};

export function xpForChallengeRating(cr: string | null | undefined): number {
  return CR_XP[String(cr ?? "").trim()] ?? 0;
}

export function nextLevelXp(level: number): number | null {
  return level >= 20 ? null : (XP_THRESHOLDS[Math.max(1, Math.min(19, level))] ?? null);
}

export function levelFromXp(xp: number): number {
  let level = 1;
  XP_THRESHOLDS.forEach((threshold, index) => {
    if (xp >= threshold) level = index + 1;
  });
  return Math.min(20, level);
}

export function encounterDifficulty(levels: number[], monsterXp: number): Difficulty {
  if (levels.length === 0 || monsterXp <= 0) return "trivial";
  const [low, moderate, high] = levels.reduce<[number, number, number]>((totals, level) => {
    const budget = ENCOUNTER_BUDGET_2024[Math.max(1, Math.min(20, level))] ?? [0, 0, 0];
    return [totals[0] + budget[0], totals[1] + budget[1], totals[2] + budget[2]];
  }, [0, 0, 0]);
  if (monsterXp < low) return "trivial";
  if (monsterXp < moderate) return "low";
  if (monsterXp < high) return "moderate";
  return "high";
}

export function shiftDifficulty(base: Difficulty, shift: number): Difficulty {
  const order: Difficulty[] = ["trivial", "low", "moderate", "high"];
  return order[Math.max(0, Math.min(order.length - 1, order.indexOf(base) + shift))] ?? base;
}

export function averageHpGain(hitDie: number, constitution: number): number {
  return Math.max(1, Math.floor(hitDie / 2) + 1 + Math.floor((constitution - 10) / 2));
}
