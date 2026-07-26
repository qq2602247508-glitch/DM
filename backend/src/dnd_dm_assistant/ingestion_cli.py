from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import NoReturn

from dnd_dm_assistant.application.content_ingestion import crawl_website, normalize_snapshot
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.content_artifacts import ArtifactStore
from dnd_dm_assistant.integrations.content.fetcher import FetchConfig, SafeHttpFetcher
from dnd_dm_assistant.integrations.content.navigation import (
    discover_snapshot_files,
    parse_navigation,
    parse_wcp_navigation,
)
from dnd_dm_assistant.integrations.content.parser import decode_html
from dnd_dm_assistant.integrations.content.repository import (
    REPOSITORIES,
    RepositoryError,
    clone_or_update,
    open_snapshot,
)
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dnd-content",
        description="Deterministic local D&D content snapshot importer",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources", help="list built-in repository profiles")

    clone = commands.add_parser("clone", help="explicitly clone or update a source snapshot")
    clone.add_argument("--source", choices=sorted(REPOSITORIES), required=True)
    clone.add_argument("--checkout", type=Path)
    clone.add_argument("--revision")
    clone.add_argument("--update", action="store_true")

    import_local = commands.add_parser("import-local", help="normalize an explicit local checkout")
    _add_snapshot_arguments(import_local)

    discover = commands.add_parser(
        "discover-local",
        help="offline dry-run: inspect navigation without writing corpus artifacts",
    )
    discover.add_argument("--checkout", type=Path, required=True)
    discover.add_argument("--content-subdir", type=Path, default=Path("."))
    discover.add_argument("--revision")

    fixtures = commands.add_parser(
        "normalize-fixtures", help="normalize the compact offline test snapshot"
    )
    fixtures.add_argument(
        "--checkout",
        type=Path,
        default=Path("backend/tests/fixtures/snapshot"),
    )
    fixtures.add_argument("--output", type=Path, required=True)
    fixtures.add_argument("--max-pages", type=int, default=20)

    crawl = commands.add_parser(
        "crawl-site",
        help="bounded robots-aware website fallback (never the default import path)",
    )
    crawl.add_argument("--output", type=Path, required=True)
    crawl.add_argument("--max-pages", type=int, default=2)
    crawl.add_argument("--navigation-url", default="/webhelplefth.htm")

    validate = commands.add_parser("validate", help="validate generated JSON/Markdown")
    validate.add_argument("--output", type=Path, required=True)
    return parser


def _add_snapshot_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--content-subdir", type=Path, default=Path("."))
    parser.add_argument("--source-profile", choices=sorted(REPOSITORIES))
    parser.add_argument("--repository-url")
    parser.add_argument("--revision")
    parser.add_argument("--ref")
    parser.add_argument("--license", default="unknown")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=20)


def _policy(settings: Settings) -> UrlPolicy:
    return UrlPolicy(
        base_url=settings.content_base_url,
        allowed_hosts=settings.allowed_content_hosts,
    )


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


async def _crawl(args: argparse.Namespace, settings: Settings) -> None:
    max_pages = min(int(args.max_pages), settings.content_max_pages)
    if max_pages < 1:
        _fail("--max-pages must be positive")
    policy = _policy(settings)
    fetch_config = FetchConfig(
        user_agent=settings.content_user_agent,
        connect_timeout_seconds=settings.content_connect_timeout_seconds,
        read_timeout_seconds=settings.content_read_timeout_seconds,
        max_response_bytes=settings.content_max_response_bytes,
        delay_seconds=settings.content_delay_seconds,
        retries=settings.content_retries,
        backoff_seconds=settings.content_backoff_seconds,
        concurrency=settings.content_concurrency,
    )
    async with SafeHttpFetcher(policy=policy, config=fetch_config) as fetcher:
        report = await crawl_website(
            fetcher=fetcher,
            policy=policy,
            store=ArtifactStore(Path(args.output)),
            max_pages=max_pages,
            navigation_url=str(args.navigation_url),
        )
    _print_json(report.model_dump(mode="json"))


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    settings = Settings()
    try:
        if args.command == "sources":
            _print_json(
                {
                    key: {
                        "default_branch": value.default_branch,
                        "declared_license": value.declared_license,
                        "preferred": value.preferred,
                        "repository_url": value.repository_url,
                    }
                    for key, value in sorted(REPOSITORIES.items())
                }
            )
            return
        if args.command == "clone":
            profile = REPOSITORIES[str(args.source)]
            checkout = (
                Path(args.checkout)
                if args.checkout
                else settings.content_checkout_root / profile.key
            )
            revision = clone_or_update(
                profile=profile,
                checkout_path=checkout,
                revision=str(args.revision) if args.revision else None,
                update=bool(args.update),
            )
            _print_json(
                {
                    "checkout": str(checkout.resolve()),
                    "declared_license": profile.declared_license,
                    "repository_url": profile.repository_url,
                    "revision": revision,
                    "source_ref": str(args.revision or profile.default_branch),
                }
            )
            return
        if args.command == "discover-local":
            snapshot = open_snapshot(
                checkout_path=Path(args.checkout),
                content_subdir=Path(args.content_subdir),
                revision=str(args.revision) if args.revision else None,
            )
            navigation = snapshot.find_navigation()
            html, warnings = decode_html(navigation.read_bytes())
            policy = _policy(settings)
            navigation_discovery = (
                parse_wcp_navigation(html, policy=policy)
                if navigation.suffix.lower() == ".wcp"
                else parse_navigation(
                    html,
                    page_url=policy.canonicalize("/webhelplefth.htm"),
                    policy=policy,
                )
            )
            discovery = (
                discover_snapshot_files(
                    snapshot,
                    policy=policy,
                    navigation=navigation_discovery,
                )
                if navigation.suffix.lower() == ".wcp"
                else navigation_discovery
            )
            _print_json(
                {
                    "aliases_deduplicated": discovery.duplicate_count,
                    "fetchable": sum(record.fetchable for record in discovery.records),
                    "records": [record.model_dump(mode="json") for record in discovery.records],
                    "rejected_urls": [
                        rejected.model_dump(mode="json") for rejected in discovery.rejected_urls
                    ],
                    "revision": snapshot.revision,
                    "warnings": list(warnings),
                }
            )
            return
        if args.command == "normalize-fixtures":
            snapshot = open_snapshot(
                checkout_path=Path(args.checkout),
                repository_url="fixture://local",
                revision="0" * 40,
                source_ref="fixture-v1",
                declared_license="synthetic-test-fixture",
            )
            report = normalize_snapshot(
                snapshot=snapshot,
                policy=_policy(settings),
                store=ArtifactStore(Path(args.output)),
                max_pages=int(args.max_pages),
                source_kind="fixture",
            )
            _print_json(report.model_dump(mode="json"))
            return
        if args.command == "import-local":
            profile_key = str(args.source_profile) if args.source_profile else None
            local_profile = REPOSITORIES[profile_key] if profile_key else None
            repository_url = (
                str(args.repository_url)
                if args.repository_url
                else local_profile.repository_url
                if local_profile
                else None
            )
            declared_license = (
                local_profile.declared_license
                if local_profile and str(args.license) == "unknown"
                else str(args.license)
            )
            source_ref = (
                str(args.ref)
                if args.ref
                else local_profile.default_branch
                if local_profile
                else None
            )
            snapshot = open_snapshot(
                checkout_path=Path(args.checkout),
                content_subdir=Path(args.content_subdir),
                repository_url=repository_url,
                revision=str(args.revision) if args.revision else None,
                source_ref=source_ref,
                declared_license=declared_license,
            )
            report = normalize_snapshot(
                snapshot=snapshot,
                policy=_policy(settings),
                store=ArtifactStore(Path(args.output)),
                max_pages=int(args.max_pages),
                source_kind="github_snapshot" if local_profile else "local_snapshot",
            )
            _print_json(report.model_dump(mode="json"))
            return
        if args.command == "crawl-site":
            asyncio.run(_crawl(args, settings))
            return
        if args.command == "validate":
            count, errors = ArtifactStore(Path(args.output)).validate()
            _print_json({"errors": list(errors), "records": count, "valid": not errors})
            if errors:
                raise SystemExit(1)
            return
        parser.error(f"unsupported command: {args.command}")
    except (RepositoryError, ValueError) as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main()
