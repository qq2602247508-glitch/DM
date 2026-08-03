import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SceneMap } from "./SceneMap";

describe("SceneMap", () => {
  it("keeps inert terrain out of the keyboard button tree", () => {
    const onCellSelect = vi.fn();
    render(
      <SceneMap
        canSelectCell={(row, col) => row === 2 && col === 2}
        grid={{ width: 3, height: 2, cell_size_ft: 5, cells: [] }}
        objects={[]}
        onCellSelect={onCellSelect}
        tokens={[]}
      />,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    const movementCell = screen.getByRole("button", { name: "格子 2,2" });
    fireEvent.click(movementCell);
    expect(onCellSelect).toHaveBeenCalledWith(2, 2);
    expect(document.querySelectorAll("[data-grid-row]")).toHaveLength(6);
  });

  it("keeps selectable targets interactive while static tokens stay readable", () => {
    const onTargetSelect = vi.fn();
    render(
      <SceneMap
        grid={{ width: 2, height: 1, cell_size_ft: 5, cells: [] }}
        objects={[]}
        onTargetSelect={onTargetSelect}
        selectableTargetKeys={new Set(["monster:m1"])}
        tokens={[
          { id: "t1", entity_id: "m1", entity_type: "monster", label: "地精", row: 1, col: 1, targetKey: "monster:m1" },
          { id: "t2", entity_id: "n1", entity_type: "npc", label: "店主", row: 1, col: 2, targetKey: "npc:n1" },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "格子 1,1 · 地精" }));
    expect(onTargetSelect).toHaveBeenCalledWith("monster:m1");
    expect(screen.getByRole("img", { name: "格子 1,2 · 店主" })).toBeInTheDocument();
  });

  it("renders unexplored and explored-but-hidden fog as visibly different states", () => {
    render(
      <SceneMap
        grid={{
          width: 3,
          height: 1,
          cell_size_ft: 5,
          fog_of_war: true,
          explored_cells: [{ row: 1, col: 1 }, { row: 1, col: 2 }],
          visible_cells: [{ row: 1, col: 1 }],
          cells: [
            { row: 1, col: 1, kind: "floor", label: "地面" },
            { row: 1, col: 2, kind: "room", label: "已探索房间" },
          ],
        }}
        objects={[]}
        tokens={[]}
      />,
    );

    expect(screen.getByText("战争迷雾：黑色为未探索，暗色为已探索但当前不可见")).toBeInTheDocument();
    const cells = [...document.querySelectorAll("[data-grid-row]")];
    expect(cells).toHaveLength(3);
    expect(cells[1]).toHaveClass("brightness-[.35]");
    expect(cells[2]).toHaveClass("bg-black");
  });
});
