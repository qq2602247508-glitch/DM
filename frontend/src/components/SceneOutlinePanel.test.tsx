import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Scene } from "../api/types";
import { buildSceneNotes, type SceneFlowStep } from "../ui/sceneOutline";
import { generateTacticalSceneGrid } from "../ui/sceneGridGenerator";
import { SceneOutlinePanel } from "./SceneOutlinePanel";

const scene: Scene = {
  id: "scene-1", campaign_id: "campaign-1", location_id: null,
  name: "暮铃酒馆", description: "接受委托", status: "active", version: 1,
  notes: buildSceneNotes(generateTacticalSceneGrid("酒馆", "酒馆"), {
    chapterTitle: "第一章", chapterOrder: 1, sceneOrder: 1,
    objective: "接受委托", opening: "描述酒馆", development: "老板出示账本",
    twist: "钟声响起", climax: "决定是否出发", transition: "前往磨坊",
  }),
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

describe("SceneOutlinePanel", () => {
  it("keeps viewing separate from advancing", () => {
    const advance = vi.fn<(target: Scene, step: SceneFlowStep) => void>();
    render(<SceneOutlinePanel
      currentSceneId={scene.id}
      currentStepId={`${scene.id}:flow:1`}
      entering={false}
      onAdvanceStep={advance}
      onEnter={vi.fn()}
      onSkipStep={vi.fn()}
      scenes={[scene]}
      skippedStepIds={new Set()}
      suggestedSceneId={null}
    />);
    const viewButtons = screen.getAllByRole("button", { name: "查看详情" });
    expect(viewButtons.length).toBeGreaterThan(0);
    fireEvent.click(viewButtons[0]!);
    expect(advance).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "完成并到下一步" }));
    expect(advance).toHaveBeenCalledTimes(1);
    expect(advance.mock.calls[0]?.[1].order).toBe(2);
  });
});
