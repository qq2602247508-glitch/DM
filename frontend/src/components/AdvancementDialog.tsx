import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactElement } from "react";

import {
  confirmBatchAdvancement,
  confirmAdvancement,
  getCharacterOptions,
  previewBatchAdvancement,
  previewAdvancement,
} from "../api/entities";
import type {
  AdvancementBatchPreview,
  AdvancementBatchRequest,
  AdvancementPreview,
  AdvancementRequest,
  Character,
} from "../api/types";
import { useToast } from "../hooks/toastContext";
import { Button } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";

const ABILITIES: Array<[string, string]> = [
  ["strength", "力量"],
  ["dexterity", "敏捷"],
  ["constitution", "体质"],
  ["intelligence", "智力"],
  ["wisdom", "感知"],
  ["charisma", "魅力"],
];

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `advance-${Date.now()}`;
}

function displayScalar(value: unknown, fallback: string): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : fallback;
}

export function AdvancementDialog({
  campaignId,
  character,
}: {
  campaignId: string;
  character: Character;
}): ReactElement {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [className, setClassName] = useState(
    character.class_name === "邪术师" ? "魔契师" : character.class_name ?? "",
  );
  const [subclassName, setSubclassName] = useState("");
  const [hpMode, setHpMode] = useState<"fixed" | "roll">("fixed");
  const [hpRoll, setHpRoll] = useState("");
  const [feat, setFeat] = useState("");
  const [abilityIncreases, setAbilityIncreases] = useState<Record<string, number>>({});
  const [featureChoices, setFeatureChoices] = useState("");
  const [spellAdditions, setSpellAdditions] = useState("");
  const [spellRemovals, setSpellRemovals] = useState("");
  const [preparedSpellNames, setPreparedSpellNames] = useState<string[]>([]);
  const [overrideReason, setOverrideReason] = useState("");
  const [preview, setPreview] = useState<AdvancementPreview | null>(null);
  const [batchPlan, setBatchPlan] = useState("");
  const [batchPreview, setBatchPreview] = useState<AdvancementBatchPreview | null>(null);
  const catalog = useQuery({
    queryKey: ["character-options", 2024, campaignId],
    queryFn: ({ signal }) => getCharacterOptions(signal, campaignId),
    enabled: open,
    staleTime: 5 * 60_000,
  });
  const selectedClass = useMemo(
    () => catalog.data?.classes.find((item) => item.name === className),
    [catalog.data, className],
  );
  const currentClassLevel = character.class_levels[className]
    ?? (
      character.class_name === className
      || (character.class_name === "邪术师" && className === "魔契师")
        ? character.level
        : 0
    );
  const targetRule = selectedClass?.levels[currentClassLevel];
  const grantsAsi = targetRule?.features.some((item) => item.includes("属性值提升")) ?? false;
  const choiceRequirements = targetRule?.choice_requirements ?? [];
  const maximumSpellLevel = Math.max(
    0,
    ...choiceRequirements.map((item) => item.maximum_spell_level ?? 0),
  );
  const canonicalClassName = className === "邪术师" ? "魔契师" : className;
  const legalSpellOptions = (catalog.data?.spells ?? []).filter((spell) => (
    spell.classes.includes(canonicalClassName)
    && spell.level <= maximumSpellLevel
  ));
  const additionNames = spellAdditions
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const selectedAdditionSpells = additionNames.map((name) => (
    legalSpellOptions.find((spell) => spell.name === name)
  ));
  const preparedTarget = choiceRequirements.find(
    (item) => item.key === "prepared_spells",
  )?.target_total ?? null;
  const currentPrepared = character.spells.filter((spell) => {
    if (typeof spell !== "object" || spell === null) return false;
    const record = spell as Record<string, unknown>;
    return Number(record.spell_level ?? record.level ?? 0) > 0 && record.prepared === true;
  }).length;

  const clearPreview = (): void => setPreview(null);
  const request = (): AdvancementRequest => ({
    character_version: character.version,
    class_name: className,
    subclass_name: subclassName || null,
    hp_mode: hpMode,
    hp_roll: hpMode === "roll" ? Number(hpRoll) : null,
    ability_increases: Object.fromEntries(
      Object.entries(abilityIncreases).filter(([, value]) => value > 0),
    ),
    feat_choice: feat || null,
    feature_choices: featureChoices.split(/[,，、]/).map((item) => item.trim()).filter(Boolean),
    spell_additions: selectedAdditionSpells.map((spell, index) => {
      const name = additionNames[index] ?? "";
      return spell
        ? {
            ...spell,
            spell_level: spell.level,
            prepared: spell.level === 0 || preparedSpellNames.includes(spell.name),
            source: "level_up_choice",
            rule_year: 2024,
          }
        : {
            name,
            prepared: preparedSpellNames.includes(name),
            source: "level_up_choice",
            rule_year: 2024,
          };
    }),
    spell_removals: spellRemovals.split(/[,，、]/).map((item) => item.trim()).filter(Boolean),
    dm_override_reason: overrideReason || null,
  });
  const batchRequest = (): AdvancementBatchRequest => {
    let steps: unknown;
    try {
      steps = JSON.parse(batchPlan);
    } catch {
      throw new Error("批量计划必须是 JSON 数组，每项为一个逐级升级选择");
    }
    if (!Array.isArray(steps) || steps.length < 2) {
      throw new Error("批量计划至少需要两个逐级升级选择");
    }
    return { character_version: character.version, steps: steps as AdvancementBatchRequest["steps"] };
  };
  const previewMutation = useMutation({
    mutationFn: () => {
      if (!className) throw new Error("请选择本级职业");
      return previewAdvancement(campaignId, character.id, request());
    },
    onSuccess: setPreview,
    onError: (error) => showToast(error instanceof Error ? error.message : "升级预览失败", "error"),
  });
  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("请先生成升级预览");
      return confirmAdvancement(campaignId, character.id, {
        ...request(),
        preview_token: preview.preview_token,
        idempotency_key: idempotencyKey(),
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["characters", campaignId] });
      void queryClient.invalidateQueries({ queryKey: ["resources", campaignId] });
      showToast(`${character.name} 的升级已由 DM 确认`);
      setOpen(false);
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "升级确认失败", "error"),
  });
  const batchPreviewMutation = useMutation({
    mutationFn: () => previewBatchAdvancement(campaignId, character.id, batchRequest()),
    onSuccess: setBatchPreview,
    onError: (error) => showToast(error instanceof Error ? error.message : "批量升级预览失败", "error"),
  });
  const batchConfirmMutation = useMutation({
    mutationFn: () => {
      if (!batchPreview) throw new Error("请先生成批量升级预览");
      return confirmBatchAdvancement(campaignId, character.id, {
        ...batchRequest(),
        preview_token: batchPreview.preview_token,
        idempotency_key: idempotencyKey(),
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["characters", campaignId] });
      void queryClient.invalidateQueries({ queryKey: ["resources", campaignId] });
      showToast(`${character.name} 的批量升级已由 DM 确认`);
      setOpen(false);
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "批量升级确认失败", "error"),
  });

  return (
    <>
      <Button
        disabled={character.level >= 20}
        onClick={() => {
          setOpen(true);
          setPreview(null);
        }}
        size="sm"
        variant="primary"
      >
        升级向导
      </Button>
      {!open ? null : (
        <div
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/85 p-4 backdrop-blur-sm"
          role="dialog"
        >
          <div className="max-h-[92vh] w-full max-w-5xl overflow-y-auto rounded-lg border border-ink-600 bg-ink-900 shadow-panel">
            <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3">
              <div>
                <h3 className="m-0 font-display text-base text-parchment-100">
                  {character.name} · {character.level} → {character.level + 1} 级
                </h3>
                <p className="m-0 text-2xs text-stone-500">D&D 5e 2024 · 完整职业成长库</p>
              </div>
              <Button onClick={() => setOpen(false)} size="sm">关闭</Button>
            </div>
            <div className="grid gap-4 p-5 lg:grid-cols-[320px_1fr]">
              <div className="space-y-3">
                <label className="block text-xs text-stone-400">
                  本级加入的职业
                  <select
                    className={`${selectCls} mt-1 w-full`}
                    onChange={(event) => {
                      setClassName(event.target.value);
                      setSubclassName("");
                      setSpellAdditions("");
                      setSpellRemovals("");
                      setPreparedSpellNames([]);
                      clearPreview();
                    }}
                    value={className}
                  >
                    <option value="">选择全部 12 个核心职业之一</option>
                    {(catalog.data?.classes ?? []).map((item) => (
                      <option key={item.source_record_id} value={item.name}>
                        {item.name} · d{item.hit_die}
                      </option>
                    ))}
                  </select>
                </label>
                {targetRule?.features.some((item) => item.includes("子职")) ? (
                  <label className="block text-xs text-stone-400">
                    本级必须选择子职业
                    <select
                      className={`${selectCls} mt-1 w-full`}
                      onChange={(event) => {
                        setSubclassName(event.target.value);
                        clearPreview();
                      }}
                      value={subclassName}
                    >
                      <option value="">选择子职业</option>
                      {(selectedClass?.subclasses ?? []).map((item) => (
                        <option key={item.source_record_id} value={item.name}>{item.name}</option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <label className="block text-xs text-stone-400">
                  生命值提升
                  <select
                    className={`${selectCls} mt-1 w-full`}
                    onChange={(event) => {
                      setHpMode(event.target.value as "fixed" | "roll");
                      clearPreview();
                    }}
                    value={hpMode}
                  >
                    <option value="fixed">采用固定平均值</option>
                    <option value="roll">掷职业生命骰</option>
                  </select>
                </label>
                {hpMode === "roll" ? (
                  <input
                    className={inputCls}
                    max={selectedClass?.hit_die ?? 12}
                    min="1"
                    onChange={(event) => {
                      setHpRoll(event.target.value);
                      clearPreview();
                    }}
                    placeholder={`d${selectedClass?.hit_die ?? "?"} 实际骰值`}
                    type="number"
                    value={hpRoll}
                  />
                ) : null}
                {grantsAsi ? (
                  <div className="rounded border border-ink-700 p-3">
                    <strong className="text-xs text-parchment-100">属性提升或专长（二选一）</strong>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {ABILITIES.map(([key, label]) => (
                        <label className="text-2xs text-stone-500" key={key}>
                          {label}
                          <input
                            className={`${inputCls} mt-1 py-1`}
                            max="2"
                            min="0"
                            onChange={(event) => {
                              setAbilityIncreases((current) => ({
                                ...current,
                                [key]: Number(event.target.value),
                              }));
                              setFeat("");
                              clearPreview();
                            }}
                            type="number"
                            value={abilityIncreases[key] ?? 0}
                          />
                        </label>
                      ))}
                    </div>
                    <select
                      className={`${selectCls} mt-2 w-full`}
                      onChange={(event) => {
                        setFeat(event.target.value);
                        setAbilityIncreases({});
                        clearPreview();
                      }}
                      value={feat}
                    >
                      <option value="">或选择 2024 专长</option>
                      {(catalog.data?.feats ?? []).map((item) => (
                        <option key={item.source_record_id} value={item.name}>{item.name}</option>
                      ))}
                    </select>
                  </div>
                ) : null}
                {choiceRequirements.length ? (
                  <div className="rounded border border-sky-800/60 bg-sky-950/15 p-3">
                    <strong className="text-xs text-sky-100">本级规则积木</strong>
                    <ul className="mb-0 mt-2 space-y-2 p-0 text-2xs text-stone-300">
                      {choiceRequirements.map((requirement) => (
                        <li className="list-none rounded border border-ink-700 p-2" key={requirement.key}>
                          <span className={requirement.strict ? "text-emerald-300" : "text-amber-300"}>
                            {requirement.strict ? "系统强制" : "DM复核"}
                          </span>
                          {" · "}{requirement.key}：{requirement.minimum === requirement.maximum
                            ? `选择 ${requirement.maximum} 项`
                            : `选择 ${requirement.minimum}–${requirement.maximum} 项`}
                          {requirement.target_total !== null ? ` · 完成后总数 ${requirement.target_total}` : ""}
                          {requirement.maximum_spell_level !== null ? ` · 最高 ${requirement.maximum_spell_level} 环` : ""}
                          <span className="mt-1 block text-stone-500">{requirement.reason}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="rounded border border-ink-700 p-2 text-2xs text-stone-500">
                    本级成长表没有额外选择；生命值、职业特性和资源变化仍会进入预览。
                  </p>
                )}
                <input
                  className={inputCls}
                  onChange={(event) => {
                    setFeatureChoices(event.target.value);
                    clearPreview();
                  }}
                  placeholder="本级特性选项（逗号分隔）"
                  value={featureChoices}
                />
                <input
                  className={inputCls}
                  list="advancement-spells"
                  onChange={(event) => {
                    setSpellAdditions(event.target.value);
                    clearPreview();
                  }}
                  placeholder="新增法术（逗号分隔）"
                  value={spellAdditions}
                />
                <datalist id="advancement-spells">
                  {legalSpellOptions.map((item) => (
                    <option key={item.source_record_id} value={item.name} />
                  ))}
                </datalist>
                {selectedAdditionSpells.some(Boolean) ? (
                  <div className="rounded border border-violet-800/60 bg-violet-950/15 p-3">
                    <strong className="text-xs text-violet-100">新增法术的准备状态</strong>
                    <p className="mb-2 mt-1 text-2xs text-stone-500">
                      戏法始终可用；有环法术只有标记“升级后准备”才进入战斗栏。
                      {preparedTarget !== null
                        ? ` 当前已准备 ${currentPrepared} 个，本级目标总数 ${preparedTarget} 个。`
                        : ""}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {selectedAdditionSpells.filter((spell) => Boolean(spell)).map((spell) => spell && (
                        <label className="rounded border border-ink-700 px-2 py-1 text-2xs text-stone-300" key={spell.source_record_id}>
                          <input
                            checked={spell.level === 0 || preparedSpellNames.includes(spell.name)}
                            className="mr-1"
                            disabled={spell.level === 0}
                            onChange={(event) => setPreparedSpellNames((current) => (
                              event.target.checked
                                ? [...new Set([...current, spell.name])]
                                : current.filter((name) => name !== spell.name)
                            ))}
                            type="checkbox"
                          />
                          {spell.name} · {spell.level === 0 ? "戏法（始终可用）" : `${spell.level}环`}
                        </label>
                      ))}
                    </div>
                  </div>
                ) : null}
                <input
                  className={inputCls}
                  onChange={(event) => {
                    setSpellRemovals(event.target.value);
                    clearPreview();
                  }}
                  placeholder="替换掉的法术（逗号分隔）"
                  value={spellRemovals}
                />
                <textarea
                  className={`${inputCls} min-h-20`}
                  onChange={(event) => {
                    setOverrideReason(event.target.value);
                    clearPreview();
                  }}
                  placeholder="DM 覆盖理由（里程碑升级、属性前置等，仅需要时填写）"
                  value={overrideReason}
                />
                <label className="block text-xs text-stone-400">
                  连续升级计划（DM JSON 数组）
                  <textarea
                    className={`${inputCls} mt-1 min-h-28 font-mono text-2xs`}
                    onChange={(event) => {
                      setBatchPlan(event.target.value);
                      setBatchPreview(null);
                    }}
                    placeholder={'[{"class_name":"战士"},{"class_name":"战士","subclass_name":"冠军"}]'}
                    value={batchPlan}
                  />
                  <span className="mt-1 block text-2xs text-stone-500">
                    每项使用本表单的升级字段（不含 character_version）。服务器会逐级校验；涉及专长、法术或未结构化扩展时仍需明确填入选择或 DM 覆盖理由。
                  </span>
                </label>
              </div>
              <div className="min-w-0">
                <div className="max-h-72 overflow-auto rounded border border-ink-700">
                  <table className="w-full text-left text-xs">
                    <thead className="sticky top-0 bg-ink-950 text-stone-500">
                      <tr>
                        <th className="px-3 py-2">等级</th>
                        <th className="px-3 py-2">PB</th>
                        <th className="px-3 py-2">获得特性</th>
                        <th className="px-3 py-2">进度资源</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedClass?.levels ?? []).map((level) => (
                        <tr
                          className={
                            level.level === currentClassLevel + 1
                              ? "border-t border-ember-700 bg-ember-950/20"
                              : "border-t border-ink-800"
                          }
                          key={level.level}
                        >
                          <td className="px-3 py-2 font-mono">{level.level}</td>
                          <td className="px-3 py-2">+{level.proficiency_bonus}</td>
                          <td className="px-3 py-2 text-parchment-100">
                            {level.features.join("、") || "—"}
                          </td>
                          <td className="px-3 py-2 text-stone-500">
                            {Object.entries(level.progression)
                              .map(([key, value]) => `${key} ${value}`)
                              .join(" · ") || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {preview ? (
                  <div className="mt-4 rounded border border-violet-800/60 bg-violet-950/20 p-4 text-sm">
                    <strong className="text-parchment-100">升级差异预览</strong>
                    <p className="mb-2 mt-1">
                      {preview.class_name} {preview.class_level}级
                      {preview.subclass_name ? ` · ${preview.subclass_name}` : ""}
                      {" · "}HP +{preview.hp_gain}
                    </p>
                    <p className="mb-1 text-xs text-stone-400">
                      新特性：{preview.features_gained.map((item) => item.name).join("、") || "无"}
                    </p>
                    {preview.feat_choice ? (
                      <p className="mb-1 text-xs text-stone-400">专长：{preview.feat_choice}</p>
                    ) : null}
                    {preview.warnings.map((warning) => (
                      <p className="mb-1 text-xs text-amber-300" key={warning}>警告：{warning}</p>
                    ))}
                    {preview.resource_updates && Object.keys(preview.resource_updates).length ? (
                      <p className="mb-1 text-xs text-sky-300">
                        资源更新：{Object.values(preview.resource_updates)
                          .map((resource) => `${displayScalar(resource.label, "职业资源")}上限 ${displayScalar(resource.max, "—")}`)
                          .join("、")}
                      </p>
                    ) : null}
                    <p className="mb-0 text-2xs text-stone-600">
                      来源：{preview.rule_reference.source_path}
                    </p>
                  </div>
                ) : (
                  <p className="mt-4 text-xs text-stone-500">
                    选择完成后生成预览。预览不会修改角色；只有 DM 确认才会一次性写入。
                  </p>
                )}
                {batchPreview ? (
                  <div className="mt-3 rounded border border-sky-800/60 bg-sky-950/20 p-3 text-xs">
                    <strong className="text-sky-100">批量升级预览：{batchPreview.from_level} → {batchPreview.to_level} 级</strong>
                    <p className="mb-0 mt-1 text-stone-400">
                      {batchPreview.steps.map((step) => `${step.class_name} ${step.class_level}级`).join(" → ")}
                    </p>
                  </div>
                ) : null}
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-ink-700 px-5 py-3">
              <Button onClick={() => setOpen(false)}>取消</Button>
              <Button
                loading={previewMutation.isPending}
                onClick={() => previewMutation.mutate()}
              >
                {preview ? "重新预览" : "生成升级预览"}
              </Button>
              <Button
                disabled={!preview}
                loading={confirmMutation.isPending}
                onClick={() => confirmMutation.mutate()}
                variant="primary"
              >
                DM 确认升级
              </Button>
              <Button
                disabled={!batchPlan.trim()}
                loading={batchPreviewMutation.isPending}
                onClick={() => batchPreviewMutation.mutate()}
              >
                批量预览
              </Button>
              <Button
                disabled={!batchPreview}
                loading={batchConfirmMutation.isPending}
                onClick={() => batchConfirmMutation.mutate()}
                variant="primary"
              >
                DM 确认批量升级
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
