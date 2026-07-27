import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildRuleBlockPlan, targetingFromRulePlan } from "../ui/ruleBlocks";
import { RuleBlockPlan } from "./RuleBlockPlan";

describe("rule block plans", () => {
  it("builds an executable area-save spell only from structured fields", () => {
    const source = {
      casting_time: "动作",
      target: "区域内每个生物",
      range: "150尺",
      radius: 20,
      cost: "动作",
      resource_key: "3环法术位",
      resource_cost: 1,
      save_ability: "敏捷",
      save_dc: 17,
      half_damage_on_save: true,
      damage: "8d6",
      damage_type: "火焰",
      duration: "立即",
      resolution_kind: "damage",
      description: "区域内目标分别进行豁免，整次施法共用一次伤害骰。",
    };

    const plan = buildRuleBlockPlan(source);
    expect(plan.automation).toBe("automatic");
    expect(plan.blocks.find((block) => block.kind === "range")?.value).toContain("20尺半径");
    expect(plan.blocks.find((block) => block.kind === "save")?.value).toContain("敏捷豁免 · DC 17");
    expect(plan.blocks.find((block) => block.kind === "effect")?.value).toBe("8d6 火焰伤害");

    render(<RuleBlockPlan source={source} />);
    const planView = screen.getByRole("region", { name: "规则执行积木" });
    expect(within(planView).getByText("可进入自动结算")).toHaveAttribute("data-automation", "automatic");
    expect(within(planView).getByText(/成功半伤/)).toBeInTheDocument();
    expect(within(planView).getByText(/3环法术位 × 1/)).toBeInTheDocument();
  });

  it("marks narrative magic as manual without inventing damage or a save", () => {
    const source = {
      name: "侦测魔法",
      casting_time: "动作",
      range: "自身",
      duration: "专注，至多10分钟",
      concentration: true,
      resolution_kind: "narrative",
      description: "感知一定范围内魔法的存在。",
    };

    const plan = buildRuleBlockPlan(source);
    expect(plan.automation).toBe("manual");
    expect(plan.blocks.some((block) => block.kind === "effect")).toBe(false);
    expect(plan.blocks.some((block) => block.kind === "save")).toBe(false);

    render(<RuleBlockPlan source={source} />);
    expect(screen.getByText("不可自动结算 · 需 DM 裁定")).toBeInTheDocument();
    expect(screen.getByText(/不会虚构伤害、范围或 DC/)).toBeInTheDocument();
    expect(screen.queryByText(/敏捷豁免/)).not.toBeInTheDocument();
  });

  it("keeps incomplete damage data partial instead of guessing its hit rule", () => {
    const plan = buildRuleBlockPlan({
      name: "未知吐息",
      damage: "2d6",
      description: "命中敌人后造成伤害。",
    });

    expect(plan.automation).toBe("partial");
    expect(plan.reason).toContain("缺少命中、豁免");
    expect(plan.blocks.some((block) => block.kind === "target")).toBe(false);
    expect(plan.blocks.some((block) => block.kind === "save")).toBe(false);
  });

  it("renders the canonical backend plan and exposes its tactical template", () => {
    const source = {
      rule_plan: {
        schema_version: "1.0",
        automation_confidence: "exact",
        automation_ready: true,
        unresolved_reasons: [],
        blocks: [
          {
            id: "target",
            kind: "target",
            mode: "area",
            disposition: "enemy",
            range_ft: 150,
            shape: "sphere",
            size_ft: 20,
          },
          {
            id: "save",
            kind: "save",
            ability: "dexterity",
            dc_source: "source_spell_save_dc",
            on_success: "half",
          },
          {
            id: "damage",
            kind: "damage",
            expression: "8d6",
            damage_type: "fire",
            shared_roll: true,
          },
        ],
      },
    };
    const plan = buildRuleBlockPlan(source);
    expect(plan.automation).toBe("automatic");
    expect(plan.blocks.find((block) => block.kind === "effect")?.value)
      .toContain("整次效果共用伤害骰");
    expect(targetingFromRulePlan(source)).toEqual({
      shape: "circle",
      rangeFt: 150,
      sizeFt: 20,
    });
  });
});
