#!/usr/bin/env python3
"""Small dependency-free event logger for the long-session acceptance runner."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def git_revision(repo_dir: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@dataclass
class AcceptanceLogger:
    root: Path
    scenario: str
    seed: int

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "screenshots").mkdir(exist_ok=True)
        (self.root / "dom").mkdir(exist_ok=True)
        self.timeline_path = self.root / "timeline.jsonl"
        self.events: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self._write_json(
            "run.json",
            {
                "scenario": self.scenario,
                "seed": self.seed,
                "started_at": now_iso(),
                "git_revision": git_revision(Path(__file__).resolve().parents[2]),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "pid": os.getpid(),
            },
        )

    def _write_json(self, name: str, value: Any) -> None:
        (self.root / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def event(
        self,
        actor: str,
        surface: str,
        action: str,
        *,
        status: str = "passed",
        request: Any = None,
        response: Any = None,
        before: Any = None,
        after: Any = None,
        duration_ms: int | None = None,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        item = {
            "seq": len(self.events) + 1,
            "at": now_iso(),
            "actor": actor,
            "surface": surface,
            "action": action,
            "status": status,
            "request": request,
            "response": response,
            "before_hash": stable_hash(before) if before is not None else None,
            "after_hash": stable_hash(after) if after is not None else None,
            "duration_ms": duration_ms,
            "evidence": evidence or [],
        }
        self.events.append(item)
        with self.timeline_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        return item

    def check(
        self,
        name: str,
        passed: bool,
        *,
        details: str = "",
        actor: str = "system",
        surface: str = "invariant",
    ) -> None:
        item = {
            "name": name,
            "passed": passed,
            "details": details,
            "actor": actor,
            "surface": surface,
            "at": now_iso(),
        }
        self.checks.append(item)
        if not passed:
            self.failures.append(item)

    def failure(self, name: str, details: str, **evidence: Any) -> None:
        item = {"name": name, "details": details, "at": now_iso(), **evidence}
        self.failures.append(item)
        self.event(
            "system",
            "runner",
            name,
            status="failed",
            response=details,
            evidence=[str(path) for path in evidence.get("paths", [])],
        )

    def finalize(self, *, status: str, fixture: Any = None) -> Path:
        finished_at = now_iso()
        self._write_json("checks.json", self.checks)
        self._write_json("failures.json", self.failures)
        self._write_json("fixture.json", fixture or {})
        run = json.loads((self.root / "run.json").read_text(encoding="utf-8"))
        run.update(
            {
                "finished_at": finished_at,
                "status": status,
                "event_count": len(self.events),
                "check_count": len(self.checks),
                "failure_count": len(self.failures),
            }
        )
        self._write_json("run.json", run)
        passed = sum(1 for item in self.checks if item["passed"])
        summary = [
            "# 跑团综合验收报告",
            "",
            f"- 场景：{self.scenario}",
            f"- 随机种子：`{self.seed}`",
            f"- 状态：**{status}**",
            f"- 操作事件：{len(self.events)}",
            f"- 检查项：{passed}/{len(self.checks)} 通过",
            f"- 失败项：{len(self.failures)}",
            "",
            "## 失败与修复",
            "",
        ]
        if self.failures:
            summary.extend(
                f"- `{item.get('name', 'unknown')}`：{item.get('details', '')}"
                for item in self.failures
            )
        else:
            summary.append("- 本次运行没有未解决失败。")
        summary.extend(
            [
                "",
                "## 证据",
                "",
                "- `timeline.jsonl`：DM、两名玩家和系统的完整操作时间线",
                "- `checks.json`：规则、同步、权限和持久化断言",
                "- `screenshots/`：浏览器关键节点截图",
                "- `dom/`：浏览器关键节点 DOM 快照",
            ]
        )
        (self.root / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
        return self.root / "summary.md"


def write_snapshot(root: Path, name: str, value: Any) -> Path:
    path = root / "dom" / f"{name}.json"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def timed_call(func: Any) -> tuple[Any, int]:
    started = time.monotonic()
    value = func()
    return value, int((time.monotonic() - started) * 1000)
