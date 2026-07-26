import type { ReactElement } from "react";

import type { Citation } from "../api/types";
import { citationToText } from "../ui/citations";
import { formatScore } from "../ui/format";
import { Badge } from "../ui/primitives";
import {
  CONTENT_TYPE_LABELS,
  EDITION_LABELS,
  OFFICIALITY_LABELS,
} from "../ui/styles";
import { CopyButton } from "../ui/widgets";

export function CitationCard({
  citation,
  index,
}: {
  citation: Citation;
  index: number;
}): ReactElement {
  const path = citation.heading_path.length > 0 ? citation.heading_path : [citation.section];
  return (
    <li className="rounded-md border border-ink-700 bg-ink-950/60 px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 text-sm font-medium text-parchment-100">
            <span className="mr-1.5 font-mono text-2xs text-stone-500">[{index + 1}]</span>
            {citation.rule_name}
          </p>
          <p className="mb-0 mt-1 truncate text-2xs text-stone-500" title={path.join(" / ")}>
            {citation.source_title}
            {citation.source_book ? ` · ${citation.source_book}` : ""} · {path.join(" / ")}
          </p>
        </div>
        <CopyButton className="shrink-0" text={citationToText(citation)} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge tone="ember">{CONTENT_TYPE_LABELS[citation.content_type]}</Badge>
        <Badge>{EDITION_LABELS[citation.edition]}</Badge>
        <Badge tone={citation.officiality === "official" ? "ok" : citation.officiality === "third_party" ? "warn" : "neutral"}>
          {OFFICIALITY_LABELS[citation.officiality]}
        </Badge>
        <span className="ml-auto font-mono text-2xs text-stone-600" title="检索相关度">
          {formatScore(citation.score)}
        </span>
      </div>
    </li>
  );
}

export function CitationList({ citations }: { citations: Citation[] }): ReactElement | null {
  if (citations.length === 0) {
    return null;
  }
  return (
    <ol className="m-0 flex list-none flex-col gap-2 p-0">
      {citations.map((citation, index) => (
        <CitationCard citation={citation} index={index} key={citation.chunk_id} />
      ))}
    </ol>
  );
}
