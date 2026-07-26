import { useState, type ReactElement } from "react";

import { ManagementPage } from "./ManagementPage";

export function StoryManagementPage(): ReactElement {
  const [tab, setTab] = useState<"quests" | "clues">("quests");
  return (
    <div>
      <div className="mx-auto flex max-w-[1200px] gap-1.5 px-4 pt-4 lg:px-6 lg:pt-6">
        <button className={`rounded-md border px-3 py-1.5 text-sm ${tab === "quests" ? "border-ember-500/60 bg-ember-500/10 text-ember-200" : "border-ink-600 text-stone-500"}`} onClick={() => setTab("quests")} type="button">任务</button>
        <button className={`rounded-md border px-3 py-1.5 text-sm ${tab === "clues" ? "border-ember-500/60 bg-ember-500/10 text-ember-200" : "border-ink-600 text-stone-500"}`} onClick={() => setTab("clues")} type="button">线索</button>
      </div>
      <ManagementPage kind={tab} />
    </div>
  );
}
