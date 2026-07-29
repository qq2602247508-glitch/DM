import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { SiteLevelPreview } from "../api/world";
import { LevelPlanDetails, SiteGrid } from "./SiteMapWorkbench";

const LEVEL: SiteLevelPreview = {
  level_index: 1,
  name: "遗迹第一层",
  description: "测试楼层",
  difficulty: "moderate",
  encounter_budget_xp: 600,
  reward_budget_gp: 120,
  layout: {
    width: 3,
    height: 2,
    cell_size_ft: 5,
    cells: [
      { row: 0, col: 0, kind: "floor", label: "地面" },
      { row: 0, col: 1, kind: "floor", label: "地面" },
      { row: 0, col: 2, kind: "wall", label: "墙" },
      { row: 1, col: 0, kind: "floor", label: "地面" },
      { row: 1, col: 1, kind: "floor", label: "地面" },
      { row: 1, col: 2, kind: "wall", label: "墙" },
    ],
  },
  rooms: [{
    room_index: 1,
    name: "守卫厅",
    room_type: "guard_room",
    description: "门边堆着破损盾牌。",
    bounds: { row: 0, col: 0, width: 2, height: 2 },
  }],
  connectors: [],
  monster_plan: [{ name: "地精守卫", quantity: 2, xp_each: 50, source: "官方", room_index: 1 }],
  npc_plan: [{ name: "受困斥候", role: "提供情报", room_index: 1 }],
  reward_plan: [{ name: "银制钥匙", value_gp: 20, category: "任务道具", room_index: 1 }],
};

function Harness() {
  const [selected, setSelected] = useState<number | null>(null);
  return (
    <>
      <SiteGrid level={LEVEL} onSelectRoom={setSelected} selectedRoomIndex={selected} />
      <LevelPlanDetails level={LEVEL} onSelectRoom={setSelected} selectedRoomIndex={selected} />
    </>
  );
}

describe("SiteMapWorkbench room plans", () => {
  it("groups monsters, NPCs and rewards by room and highlights that room on the map", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);

    await user.click(screen.getByText(/房间 1 · 守卫厅/));
    expect(screen.getByText(/地精守卫 × 2/)).toBeInTheDocument();
    expect(screen.getByText("受困斥候")).toBeInTheDocument();
    expect(screen.getByText(/银制钥匙 · 20 gp/)).toBeInTheDocument();
    expect(container.querySelector('[data-room-index="1"].ring-cyan-300')).not.toBeNull();
  });
});
