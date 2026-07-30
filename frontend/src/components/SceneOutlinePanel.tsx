import { useEffect, useMemo, useState } from "react";

import type { Scene } from "../api/types";
import { Badge, Button } from "../ui/primitives";
import {
  buildSceneFlow, readSceneStoryOutline, sortScenesByOutline, type SceneFlowStep,
} from "../ui/sceneOutline";

const KIND_LABELS: Record<SceneFlowStep["kind"], string> = {
  setup: "现场",
  hook: "目标",
  interaction: "互动",
  challenge: "裁定",
  choice: "选择",
  complication: "变化",
  resolution: "结算",
  transition: "转场",
};

export function SceneOutlinePanel({
  currentSceneId,
  currentStepId,
  entering,
  onAdvanceStep,
  onEnter,
  onSkipStep,
  scenes,
  skippedStepIds,
  suggestedSceneId,
}: {
  currentSceneId: string;
  currentStepId: string | null;
  entering: boolean;
  onAdvanceStep: (scene: Scene, step: SceneFlowStep) => void;
  onEnter: (scene: Scene, source: "manual" | "ai") => void;
  onSkipStep: (scene: Scene, step: SceneFlowStep, nextStep: SceneFlowStep | null) => void;
  scenes: Scene[];
  skippedStepIds: Set<string>;
  suggestedSceneId: string | null;
}) {
  const ordered = useMemo(() => sortScenesByOutline(scenes), [scenes]);
  const [expandedSceneId, setExpandedSceneId] = useState(currentSceneId);
  const [detailStepId, setDetailStepId] = useState<string | null>(null);
  useEffect(() => {
    if (currentSceneId) setExpandedSceneId(currentSceneId);
  }, [currentSceneId]);
  const chapters = useMemo(() => {
    const result = new Map<string, Scene[]>();
    ordered.forEach((scene, index) => {
      const chapter = readSceneStoryOutline(scene, index + 1).chapterTitle;
      result.set(chapter, [...(result.get(chapter) ?? []), scene]);
    });
    return [...result.entries()];
  }, [ordered]);

  return (
    <div className="space-y-2" data-testid="scene-outline">
      <div className="rounded border border-violet-900/60 bg-violet-950/15 p-2 text-2xs leading-5 text-stone-400">
        <strong className="text-violet-200">流程是导航，不是剧本。</strong>
        <span className="block">“查看详情”只展开说明；只有“推进到这里”才记录进度并通知副 DM。</span>
      </div>
      {chapters.map(([chapter, chapterScenes]) => {
        const containsCurrent = chapterScenes.some((scene) => scene.id === currentSceneId);
        return (
          <details className="rounded border border-ink-700 bg-ink-950/45" key={chapter} open={containsCurrent}>
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-parchment-100">
              {chapter} <span className="text-stone-600">· {chapterScenes.length} Scenes</span>
            </summary>
            <div className="space-y-2 border-t border-ink-700 p-2">
              {chapterScenes.map((scene) => {
                const globalIndex = ordered.findIndex((item) => item.id === scene.id);
                const outline = readSceneStoryOutline(scene, globalIndex + 1);
                const flow = buildSceneFlow(scene, globalIndex + 1);
                const current = scene.id === currentSceneId;
                const expanded = scene.id === expandedSceneId;
                const suggested = scene.id === suggestedSceneId;
                const currentIndex = current ? flow.findIndex((step) => step.id === currentStepId) : -1;
                return (
                  <article className={`rounded border p-2 ${current ? "border-ember-500 bg-ember-950/20" : suggested ? "border-violet-600 bg-violet-950/15" : "border-ink-700 bg-ink-950/60"}`} key={scene.id}>
                    <button aria-expanded={expanded} className="flex w-full items-center gap-2 text-left" onClick={() => setExpandedSceneId((value) => value === scene.id ? "" : scene.id)} type="button">
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-ink-600 font-mono text-2xs text-ember-200">{outline.sceneOrder}</span>
                      <strong className="min-w-0 flex-1 truncate text-xs text-parchment-100">Scene {outline.sceneOrder} · {scene.name}</strong>
                      {current ? <Badge tone="ok">当前</Badge> : null}
                      {suggested ? <Badge tone="ai">AI建议</Badge> : null}
                      <span className="text-stone-500">{expanded ? "−" : "+"}</span>
                    </button>
                    {expanded ? (
                      <div className="mt-2 border-t border-ink-700 pt-2">
                        <p className="m-0 rounded bg-ink-950/50 px-2 py-1.5 text-2xs leading-5 text-stone-400"><b className="text-ember-200">本场目标：</b>{outline.objective}</p>
                        <ol className="m-0 mt-2 space-y-1.5 p-0">
                          {flow.map((step, index) => {
                            const isCurrent = current && step.id === currentStepId;
                            const skipped = skippedStepIds.has(step.id);
                            const completed = current && currentIndex >= 0 && index < currentIndex && !skipped;
                            const detailsOpen = detailStepId === step.id;
                            const nextStep = flow[index + 1] ?? null;
                            return (
                              <li className={`list-none rounded border p-2 ${isCurrent ? "border-ember-500 bg-ember-950/30 ring-1 ring-ember-700/40" : completed ? "border-emerald-900/50 bg-emerald-950/10" : skipped ? "border-ink-800 bg-ink-950/30 opacity-60" : "border-ink-800 bg-ink-950/50"}`} key={step.id}>
                                <div className="flex items-start gap-2">
                                  <span className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border font-mono text-[10px] ${isCurrent ? "border-ember-400 text-ember-200" : completed ? "border-emerald-700 text-emerald-300" : "border-ink-600 text-stone-500"}`}>{completed ? "✓" : skipped ? "–" : step.order}</span>
                                  <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-1">
                                      <strong className="text-xs text-parchment-100">{step.title}</strong>
                                      <Badge>{KIND_LABELS[step.kind]}</Badge>
                                      {isCurrent ? <Badge tone="warn">进行中</Badge> : completed ? <Badge tone="ok">完成</Badge> : skipped ? <Badge>跳过</Badge> : null}
                                    </div>
                                    <p className="mb-0 mt-1 line-clamp-2 text-2xs leading-5 text-stone-500">{step.instruction}</p>
                                  </div>
                                </div>
                                <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                                  <Button onClick={() => setDetailStepId(detailsOpen ? null : step.id)} size="sm">{detailsOpen ? "收起详情" : "查看详情"}</Button>
                                  {current ? <Button disabled={entering || skipped} loading={entering && isCurrent} onClick={() => onAdvanceStep(scene, isCurrent && nextStep ? nextStep : step)} size="sm" variant={isCurrent ? "primary" : "ai"}>{isCurrent && nextStep ? "完成并到下一步" : "推进到这里"}</Button> : null}
                                  {current && !isCurrent && !completed && !skipped ? <Button disabled={entering} onClick={() => onSkipStep(scene, step, nextStep)} size="sm">跳过</Button> : null}
                                </div>
                                {detailsOpen ? (
                                  <div className="mt-2 space-y-2 border-t border-ink-700 pt-2 text-2xs leading-5">
                                    <p className="m-0 text-stone-300"><b className="text-parchment-100">怎么推进：</b>{step.instruction}</p>
                                    <p className="m-0 text-amber-200/80"><b>DM 注意：</b>{step.dmNote}</p>
                                  </div>
                                ) : null}
                              </li>
                            );
                          })}
                        </ol>
                        {!current ? <div className="flex justify-end pt-2"><Button disabled={entering} loading={entering} onClick={() => onEnter(scene, suggested ? "ai" : "manual")} size="sm" variant={suggested ? "ai" : "primary"}>进入此 Scene</Button></div> : null}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </details>
        );
      })}
      {scenes.length === 0 ? <p className="m-0 rounded border border-dashed border-ink-700 p-3 text-xs text-stone-600">还没有 Scene。请切换到“开团前备团”创建或导入。</p> : null}
    </div>
  );
}
