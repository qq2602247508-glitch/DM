import { useQuery } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { getRuleDocument, searchKnowledge } from "../api/knowledge";
import type { ContentType, Edition, SearchHit, SearchQuery } from "../api/types";
import { Panel } from "../components/Panel";
import { CitationList } from "../components/Citations";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { CONTENT_TYPE_LABELS, EDITION_LABELS, inputCls, selectCls } from "../ui/styles";
import { Badge, EmptyState, LoadingBlock } from "../ui/primitives";
import { formatScore } from "../ui/format";

const TYPES: ContentType[] = ["spells", "monsters", "classes", "items", "rules", "conditions", "feats", "backgrounds"];
const CURRENT_EDITIONS: Edition[] = ["2024", "2025"];
const LEGACY_EDITIONS: Edition[] = ["2014", "legacy"];

function HitCard({ hit }: { hit: SearchHit }): ReactElement {
  const [expanded, setExpanded] = useState(false);
  const { chunk } = hit;
  const document = useQuery({
    queryKey: ["rule-document", chunk.record_id],
    queryFn: ({ signal }) => getRuleDocument(chunk.record_id, signal),
    enabled: expanded,
    staleTime: Number.POSITIVE_INFINITY,
  });
  return (
    <article className="border-b border-ink-700/60 py-4 last:border-0">
      <button className="w-full text-left" onClick={() => setExpanded((value) => !value)} type="button">
        <div className="flex flex-wrap items-start gap-2">
          <h3 className="m-0 flex-1 font-display text-base font-normal text-parchment-100">{chunk.name}</h3>
          <Badge tone="ember">{CONTENT_TYPE_LABELS[chunk.content_type]}</Badge>
          <Badge>{EDITION_LABELS[chunk.edition]}</Badge>
          <span className="text-2xs text-stone-600">{formatScore(hit.score)}</span>
        </div>
        <p className={`prose-block mb-0 mt-2 text-sm text-stone-400 ${expanded ? "" : "line-clamp-3"}`}>{chunk.text}</p>
      </button>
      {expanded ? (
        <div className="mt-3 border-l-2 border-ember-500/50 pl-3">
          <p className="m-0 text-2xs text-stone-500">{chunk.section || "正文"} · {chunk.source_title}</p>
          {document.isLoading ? <LoadingBlock label="正在读取完整规则条目…" /> : null}
          {document.isError ? <p className="text-xs text-red-300">完整条目读取失败，下面仍保留检索片段与来源。</p> : null}
          {document.data ? (
            <div className="mt-3 max-h-[36rem] overflow-y-auto rounded-md border border-ink-700 bg-ink-950/60 p-4">
              <p className="prose-block m-0 whitespace-pre-wrap text-sm leading-7 text-stone-300">
                {document.data.content_plain_text}
              </p>
            </div>
          ) : null}
          <CitationList citations={[{
            citation_id: 1, chunk_id: chunk.chunk_id, record_id: chunk.record_id,
            rule_name: chunk.name, source_title: chunk.source_title, canonical_url: chunk.canonical_url,
            section: chunk.section, heading_path: chunk.heading_path, content_type: chunk.content_type,
            edition: chunk.edition, officiality: chunk.officiality, source_book: chunk.source_book,
            repository_url: chunk.repository_url, source_relative_path: chunk.source_relative_path,
            source_ref: chunk.source_ref, source_revision: chunk.source_revision, score: hit.score,
          }]} />
        </div>
      ) : null}
    </article>
  );
}

export function RulesPage(): ReactElement {
  const [text, setText] = useState("");
  const [type, setType] = useState<ContentType | "">("");
  const [edition, setEdition] = useState<Edition | "">("");
  const [showLegacy, setShowLegacy] = useState(false);
  const debounced = useDebouncedValue(text.trim(), 350);
  const query: SearchQuery = {
    text: debounced,
    top_k: 12,
    ...(type ? { content_types: [type] } : {}),
    ...(edition ? { editions: [edition] } : {}),
  };
  const search = useQuery({
    queryKey: ["knowledge-search", query],
    queryFn: ({ signal }) => searchKnowledge(query, signal),
    enabled: debounced.length >= 2,
  });
  const hits = search.data ?? [];
  return (
    <div className="mx-auto max-w-[1200px] p-4 lg:p-6">
      <Panel eyebrow="D&D5e 知识库" title="规则搜索">
        <div className="grid gap-2 md:grid-cols-[1fr_10rem_12rem]">
          <input autoFocus className={inputCls} onChange={(event) => setText(event.target.value)} placeholder="搜索火球术、专注、借机攻击、狼人…" value={text} />
          <select className={selectCls} onChange={(event) => setType(event.target.value as ContentType | "")} value={type}>
            <option value="">全部分类</option>
            {TYPES.map((item) => <option key={item} value={item}>{CONTENT_TYPE_LABELS[item]}</option>)}
          </select>
          <select className={selectCls} onChange={(event) => setEdition(event.target.value as Edition | "")} value={edition}>
            <option value="">D&D 5e 当前规则</option>
            {CURRENT_EDITIONS.map((item) => <option key={item} value={item}>{EDITION_LABELS[item]}</option>)}
            {showLegacy ? <optgroup label="Legacy 兼容">
              {LEGACY_EDITIONS.map((item) => <option key={item} value={item}>{EDITION_LABELS[item]}</option>)}
            </optgroup> : null}
          </select>
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="m-0 text-2xs text-stone-600">统一使用 D&D 5e；默认检索官方 2024 核心规则与 2025 补充内容。</p>
          <label className="flex items-center gap-1.5 text-2xs text-stone-600">
            <input
              checked={showLegacy}
              onChange={(event) => {
                setShowLegacy(event.target.checked);
                if (!event.target.checked && (edition === "2014" || edition === "legacy")) setEdition("");
              }}
              type="checkbox"
            />
            显示 2014 / Legacy 兼容资料
          </label>
        </div>
      </Panel>
      <Panel className="mt-4" eyebrow="检索结果" title={debounced ? `${hits.length} 条匹配` : "输入关键词开始搜索"}>
        {search.isLoading ? <LoadingBlock label="正在检索本地规则库…" /> : null}
        {search.isError ? <p className="m-0 py-6 text-sm text-red-300">规则索引暂时不可用，请检查本地 Qdrant 与 Ollama。</p> : null}
        {!search.isLoading && !search.isError && debounced.length >= 2 && hits.length === 0 ? <EmptyState title="没有找到匹配规则" hint="尝试更短的关键词，或切换版本 / 分类。" /> : null}
        {!search.isLoading && debounced.length < 2 ? <EmptyState title="本地规则库已就绪" hint="支持法术、怪物、职业、物品、状态与战斗规则。" /> : null}
        {hits.map((hit) => <HitCard hit={hit} key={hit.chunk.chunk_id} />)}
      </Panel>
    </div>
  );
}
