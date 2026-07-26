from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TextIO

from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.content import ContentType, Edition
from dnd_dm_assistant.domain.rag import IndexStats, SearchQuery
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dnd-rag",
        description="Offline-first D&D knowledge index, search, and grounded answering",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="incrementally index validated Phase 2 JSON")
    index.add_argument("--corpus", type=Path)
    index.add_argument("--full-rebuild", action="store_true")

    commands.add_parser("status", help="show local vector index status")

    search = commands.add_parser("search", help="search the local rules index")
    search.add_argument("query")
    _add_search_arguments(search)

    answer = commands.add_parser("answer", help="answer only from retrieved local evidence")
    answer.add_argument("question")
    _add_search_arguments(answer)
    return parser


def _add_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--candidate-k", type=int)
    parser.add_argument("--min-score", type=float)
    parser.add_argument(
        "--content-type", action="append", choices=[value.value for value in ContentType]
    )
    parser.add_argument("--edition", action="append", choices=[value.value for value in Edition])
    parser.add_argument("--source-book", action="append")
    parser.add_argument("--all-editions", action="store_true")
    parser.add_argument("--allow-unknown", action="store_true")
    parser.add_argument("--allow-third-party", action="store_true")


def _print_json(value: object, *, stream: TextIO = sys.stdout) -> None:
    print(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str),
        file=stream,
    )


def _query(args: argparse.Namespace, settings: Settings, text: str) -> SearchQuery:
    return SearchQuery(
        text=text,
        top_k=int(args.top_k or settings.rag_search_top_k),
        candidate_k=int(args.candidate_k or settings.rag_search_candidate_k),
        min_score=(
            float(args.min_score) if args.min_score is not None else settings.rag_search_min_score
        ),
        content_types=tuple(ContentType(value) for value in (args.content_type or [])),
        editions=tuple(Edition(value) for value in (args.edition or [])),
        source_books=tuple(args.source_book or []),
        current_official=not bool(args.all_editions),
        allow_unknown=bool(args.allow_unknown),
        allow_third_party=bool(args.allow_third_party),
    )


async def _run(args: argparse.Namespace, settings: Settings) -> None:
    runtime = RuntimeIntegrations(settings)
    try:
        if args.command == "status":
            _print_json((await runtime.status()).model_dump(mode="json"))
            return
        if args.command == "index":

            def progress(stats: IndexStats) -> None:
                _print_json(
                    {
                        "progress": {
                            "discovered": stats.discovered,
                            "indexed_records": stats.indexed_records,
                            "chunks_upserted": stats.chunks_upserted,
                            "rejected": stats.rejected,
                        }
                    },
                    stream=sys.stderr,
                )

            index_result = await runtime.index(
                corpus_root=Path(args.corpus) if args.corpus else None,
                full_rebuild=bool(args.full_rebuild),
                progress=progress,
            )
            _print_json(index_result.model_dump(mode="json"))
            return
        if args.command == "search":
            query = _query(args, settings, str(args.query))
            hits = await runtime.search(query)
            _print_json({"hits": [hit.model_dump(mode="json") for hit in hits]})
            return
        if args.command == "answer":
            query = _query(args, settings, str(args.question))
            answer_result = await runtime.answer(str(args.question), query)
            _print_json(answer_result.model_dump(mode="json"))
            return
        raise SystemExit(f"unsupported command: {args.command}")
    finally:
        await runtime.close()


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    asyncio.run(_run(args, Settings()))
