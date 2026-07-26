import type { Citation } from "../api/types";
import { EDITION_LABELS } from "./styles";

/** Plain-text form used when copying a citation for notes or handouts. */
export function citationToText(citation: Citation): string {
  const path =
    citation.heading_path.length > 0 ? citation.heading_path.join(" / ") : citation.section;
  const book = citation.source_book ? ` · ${citation.source_book}` : "";
  return `${citation.rule_name} — ${citation.source_title}${book} · ${path} · ${
    EDITION_LABELS[citation.edition]
  } · ${citation.canonical_url}`;
}
