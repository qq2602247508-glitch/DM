import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Monster, Npc } from "../api/types";
import { SceneEntityDetailDialog } from "./SceneEntityDetailDialog";

const VERSIONED = {
  id: "entity-1",
  campaign_id: "campaign-1",
  created_at: "2026-07-27T00:00:00Z",
  updated_at: "2026-07-27T00:00:00Z",
  version: 1,
};

const NPC: Npc = {
  ...VERSIONED,
  name: "守门人伊莱",
  description: "旧教堂的守门人。",
  alignment: "中立",
  attitude: "警惕",
  personality: "寡言",
  goal: "保护地下室入口",
  fear: "身份暴露",
  armor_class: 13,
  hp: 18,
  max_hp: 18,
  speed: 30,
  ability_scores: { strength: 10, dexterity: 14, constitution: 12, intelligence: 11, wisdom: 13, charisma: 9 },
  challenge_rating: "1/2",
  actions: [{ name: "短剑", description: "近战武器攻击。", damage: "1d6+2", range: "5尺", attack_bonus: 4 }],
  equipment: [{ name: "地下室钥匙", description: "黄铜钥匙。", category: "key", quantity: 1, unit_weight_lb: 0.1, price_cp: 50, interactive_note: null, hidden: true }],
  relationship: "尚未建立",
  secrets: "受到了威胁",
  known_information: "知道仪式时间",
  location_id: null,
  status: "active",
};

const MONSTER: Monster = {
  ...VERSIONED,
  name: "夺心魔",
  source_record_id: "monster:mind-flayer",
  source_name: "Monster Manual 2025",
  armor_class: 15,
  hp: 71,
  max_hp: 71,
  speed: 30,
  ability_scores: { strength: 11, dexterity: 12, constitution: 12, intelligence: 19, wisdom: 17, charisma: 17 },
  challenge_rating: "7",
  actions: [{ name: "心灵震爆", description: "锥形心灵能量。", damage: "4d8+4", range: "60尺锥形", save_dc: 15, save_ability: "智力", recharge: "5–6" }],
  notes: "高智力敌人。",
};

describe("SceneEntityDetailDialog", () => {
  it("shows NPC motives, secrets, actions and equipment", async () => {
    const onClose = vi.fn();
    render(<SceneEntityDetailDialog entity={NPC} entityType="npc" onClose={onClose} />);

    expect(screen.getByRole("dialog", { name: /守门人伊莱NPC 原子详情/ })).toBeInTheDocument();
    expect(screen.getByText("保护地下室入口")).toBeInTheDocument();
    expect(screen.getByText("受到了威胁")).toBeInTheDocument();
    expect(screen.getByText("1d6+2")).toBeInTheDocument();
    expect(screen.getByText(/地下室钥匙/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "关闭NPC 原子详情" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows monster provenance and rule action details", () => {
    render(<SceneEntityDetailDialog entity={MONSTER} entityType="monster" onClose={vi.fn()} />);

    expect(screen.getByText("Monster Manual 2025")).toBeInTheDocument();
    expect(screen.getByText("心灵震爆")).toBeInTheDocument();
    expect(screen.getByText("智力 DC 15")).toBeInTheDocument();
    expect(screen.getByText("恢复 / 限制：5–6")).toBeInTheDocument();
  });
});
