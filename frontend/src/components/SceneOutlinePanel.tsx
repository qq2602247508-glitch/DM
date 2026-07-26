import { useEffect, useMemo, useState } from "react";

import type { Scene } from "../api/types";
import { Badge, Button } from "../ui/primitives";
import {
  readSceneStoryOutline, sortScenesByOutline,
} from "../ui/sceneOutline";

export function SceneOutlinePanel({
  currentSceneId,
  entering,
  onEnter,
  scenes,
  suggestedSceneId,
}: {
  currentSceneId: string;
  entering: boolean;
  onEnter: (scene: Scene, source: "manual" | "ai") => void;
  scenes: Scene[];
  suggestedSceneId: string | null;
}) {
  const ordered = useMemo(() => sortScenesByOutline(scenes), [scenes]);
  const [expandedSceneId, setExpandedSceneId] = useState(currentSceneId);
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
      <p className="m-0 text-2xs leading-5 text-stone-500">
        点击 Scene 查看起承转合；“进入”才会真正切换当前 Scene，并在中间生成转场记录。
      </p>
      {chapters.map(([chapter, chapterScenes]) => {
        const containsCurrent = chapterScenes.some((scene) => scene.id === currentSceneId);
        return (
          <details
            className="rounded border border-ink-700 bg-ink-950/45"
            key={chapter}
            open={containsCurrent}
          >
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-parchment-100">
              {chapter} <span className="text-stone-600">· {chapterScenes.length} Scenes</span>
            </summary>
            <div className="space-y-2 border-t border-ink-700 p-2">
              {chapterScenes.map((scene, index) => {
                const outline = readSceneStoryOutline(scene, index + 1);
                const current = scene.id === currentSceneId;
                const expanded = scene.id === expandedSceneId;
                const suggested = scene.id === suggestedSceneId;
                return (
                  <article
                    className={`rounded border p-2 ${
                      current
                        ? "border-ember-500 bg-ember-950/20"
                        : suggested
                          ? "border-violet-600 bg-violet-950/15"
                          : "border-ink-700 bg-ink-950/60"
                    }`}
                    key={scene.id}
                  >
                    <button
                      aria-expanded={expanded}
                      className="flex w-full items-center gap-2 text-left"
                      onClick={() => setExpandedSceneId((value) => value === scene.id ? "" : scene.id)}
                      type="button"
                    >
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-ink-600 font-mono text-2xs text-ember-200">
                        {outline.sceneOrder}
                      </span>
                      <strong className="min-w-0 flex-1 truncate text-xs text-parchment-100">
                        Scene {outline.sceneOrder} · {scene.name}
                      </strong>
                      {current ? <Badge tone="ok">当前</Badge> : null}
                      {suggested ? <Badge tone="ai">AI建议</Badge> : null}
                      <span className="text-stone-500">{expanded ? "−" : "+"}</span>
                    </button>
                    {expanded ? (
                      <div className="mt-2 space-y-1 border-t border-ink-700 pt-2 text-2xs leading-5 text-stone-400">
                        <p className="m-0"><b className="text-ember-200">目标：</b>{outline.objective}</p>
                        <p className="m-0"><b className="text-stone-300">起：</b>{outline.opening}</p>
                        <p className="m-0"><b className="text-stone-300">承：</b>{outline.development}</p>
                        <p className="m-0"><b className="text-stone-300">转：</b>{outline.twist}</p>
                        <p className="m-0"><b className="text-stone-300">合：</b>{outline.climax}</p>
                        <p className="m-0"><b className="text-violet-200">转场：</b>{outline.transition}</p>
                        {!current ? (
                          <div className="flex justify-end pt-1">
                            <Button
                              disabled={entering}
                              loading={entering}
                              onClick={() => onEnter(scene, suggested ? "ai" : "manual")}
                              size="sm"
                              variant={suggested ? "ai" : "primary"}
                            >
                              进入此 Scene
                            </Button>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </details>
        );
      })}
      {scenes.length === 0 ? (
        <p className="m-0 rounded border border-dashed border-ink-700 p-3 text-xs text-stone-600">
          还没有 Scene。请切换到“开团前备团”创建或导入。
        </p>
      ) : null}
    </div>
  );
}
