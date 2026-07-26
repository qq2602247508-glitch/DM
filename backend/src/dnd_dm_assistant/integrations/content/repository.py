from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy


class RepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepositoryProfile:
    key: str
    repository_url: str
    default_branch: str
    declared_license: str
    preferred: bool = False


REPOSITORIES: dict[str, RepositoryProfile] = {
    "5echm_web": RepositoryProfile(
        key="5echm_web",
        repository_url="https://github.com/DND5eChm/5echm_web.git",
        default_branch="pages",
        declared_license="unknown",
    ),
    "dnd5e_chm": RepositoryProfile(
        key="dnd5e_chm",
        repository_url="https://github.com/DND5eChm/DND5e_chm.git",
        default_branch="main",
        declared_license="GPL-3.0",
        preferred=True,
    ),
    "srd52": RepositoryProfile(
        key="srd52",
        repository_url="https://github.com/DND5eChm/SRD5.2Chm.git",
        default_branch="main",
        declared_license="CC-BY-4.0",
    ),
}


@dataclass(frozen=True)
class Snapshot:
    checkout_root: Path
    content_root: Path
    repository_url: str | None
    revision: str
    source_ref: str | None
    declared_license: str
    snapshot_at: datetime

    def resolve_url(self, canonical_url: str) -> tuple[Path, str]:
        decoded = unquote(urlsplit(canonical_url).path).lstrip("/")
        segments = Path(decoded).parts
        if not decoded or any(segment in {"", ".", ".."} for segment in segments):
            raise RepositoryError(f"unsafe or empty repository-relative URL path: {decoded}")
        candidate = (self.content_root / Path(*segments)).resolve()
        content_root = self.content_root.resolve()
        if not candidate.is_relative_to(content_root):
            raise RepositoryError(f"path escapes snapshot: {decoded}")
        if candidate.is_symlink():
            raise RepositoryError(f"symlink source file rejected: {decoded}")
        if not candidate.is_file():
            raise RepositoryError(f"snapshot file does not exist: {decoded}")
        relative = candidate.relative_to(self.checkout_root.resolve()).as_posix()
        return candidate, relative

    def find_navigation(self) -> Path:
        direct = self.content_root / "webhelplefth.htm"
        if direct.is_file() and not direct.is_symlink():
            return direct
        matches = sorted(
            path
            for path in self.content_root.glob("*/webhelplefth.htm")
            if path.is_file() and not path.is_symlink()
        )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RepositoryError("multiple webhelplefth.htm manifests found")
        primary_wcp = self.content_root / "不全书.wcp"
        if primary_wcp.is_file() and not primary_wcp.is_symlink():
            return primary_wcp
        wcp_matches = sorted(
            path
            for path in self.content_root.glob("*.wcp")
            if path.is_file() and not path.is_symlink()
        )
        if len(wcp_matches) == 1:
            return wcp_matches[0]
        raise RepositoryError("expected one webhelplefth.htm or one root WinCHM .wcp manifest")


def clone_or_update(
    *,
    profile: RepositoryProfile,
    checkout_path: Path,
    revision: str | None = None,
    update: bool = False,
) -> str:
    target_revision = revision or profile.default_branch
    checkout_path.parent.mkdir(parents=True, exist_ok=True)
    if checkout_path.exists():
        if not update:
            raise RepositoryError("checkout already exists; pass --update explicitly")
        _run_git(
            (
                "git",
                "-C",
                str(checkout_path),
                "fetch",
                "--depth=1",
                "--filter=blob:none",
                "origin",
                target_revision,
            )
        )
        _run_git(("git", "-C", str(checkout_path), "checkout", "--detach", "FETCH_HEAD"))
    else:
        _run_git(
            (
                "git",
                "clone",
                "--depth=1",
                "--filter=blob:none",
                "--single-branch",
                "--branch",
                target_revision,
                profile.repository_url,
                str(checkout_path),
            )
        )
    return git_revision(checkout_path)


def git_revision(checkout_path: Path) -> str:
    output = _run_git(("git", "-C", str(checkout_path), "rev-parse", "HEAD")).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", output):
        raise RepositoryError(f"invalid Git revision: {output!r}")
    return output


def git_remote(checkout_path: Path) -> str | None:
    try:
        output = _run_git(("git", "-C", str(checkout_path), "remote", "get-url", "origin")).strip()
    except RepositoryError:
        return None
    return output or None


def open_snapshot(
    *,
    checkout_path: Path,
    content_subdir: Path = Path("."),
    repository_url: str | None = None,
    revision: str | None = None,
    declared_license: str = "unknown",
    source_ref: str | None = None,
) -> Snapshot:
    checkout_root = checkout_path.resolve()
    content_root = (checkout_root / content_subdir).resolve()
    if not checkout_root.is_dir() or not content_root.is_dir():
        raise RepositoryError("checkout/content path is not a directory")
    if not content_root.is_relative_to(checkout_root):
        raise RepositoryError("content subdirectory escapes checkout")
    resolved_revision = revision or git_revision(checkout_root)
    if not re.fullmatch(r"[0-9a-f]{40}", resolved_revision):
        raise RepositoryError("snapshot revision must be an exact 40-character commit SHA")
    snapshot_at = (
        git_commit_timestamp(checkout_root, resolved_revision)
        if (checkout_root / ".git").exists()
        else datetime(1970, 1, 1, tzinfo=UTC)
    )
    return Snapshot(
        checkout_root=checkout_root,
        content_root=content_root,
        repository_url=repository_url or git_remote(checkout_root),
        revision=resolved_revision,
        source_ref=source_ref,
        declared_license=declared_license,
        snapshot_at=snapshot_at,
    )


def canonical_website_url(relative_path: str, policy: UrlPolicy) -> str:
    return policy.canonicalize(f"/{relative_path.lstrip('/')}")


def git_commit_timestamp(checkout_path: Path, revision: str) -> datetime:
    output = _run_git(
        ("git", "-C", str(checkout_path), "show", "-s", "--format=%cI", revision)
    ).strip()
    try:
        value = datetime.fromisoformat(output)
    except ValueError as exc:
        raise RepositoryError(f"invalid Git commit timestamp: {output!r}") from exc
    if value.tzinfo is None:
        raise RepositoryError("Git commit timestamp omitted timezone")
    return value


def _run_git(arguments: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else ""
        detail = f": {stderr}" if stderr else ""
        raise RepositoryError(f"Git command failed{detail}") from exc
    return completed.stdout
