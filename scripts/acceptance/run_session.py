#!/usr/bin/env python3
"""Fast, API-driven three-actor acceptance run.

This is deliberately not a replacement for browser E2E.  It advances the
boring parts of a three-hour-equivalent session through the same public API,
then leaves a fixture and a JSONL timeline for the browser suite to inspect.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from report import AcceptanceLogger

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "scripts" / "create-comprehensive-test-template.py"


def call(
    client: httpx.Client,
    logger: AcceptanceLogger,
    actor: str,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    expected: set[int] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    expected = expected or {200, 201}
    response = client.request(method, path, json=json_body, headers=headers)
    body: dict[str, Any]
    try:
        parsed = response.json()
        body = parsed if isinstance(parsed, dict) else {"value": parsed}
    except ValueError:
        body = {"text": response.text}
    logger.event(
        actor,
        "api",
        f"{method} {path}",
        status="passed" if response.status_code in expected else "failed",
        request=json_body,
        response={"status": response.status_code, "body": body},
    )
    if response.status_code not in expected:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {body}")
    return body


def run_template(base_url: str) -> dict[str, Any]:
    env = {**os.environ, "DND_DM_ACCEPTANCE_BASE": base_url}
    completed = subprocess.run(
        [sys.executable, str(TEMPLATE)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("DND_DM_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1"))
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--keep", action="store_true", help="保留验收战役，供浏览器套件继续使用")
    args = parser.parse_args()

    logger = AcceptanceLogger(args.report_dir, "D&D 5e 三端三小时等价冒险", args.seed)
    fixture: dict[str, Any] = {}
    # Local acceptance must never inherit a user's SOCKS/HTTP proxy.  Apart
    # from being unnecessary for loopback, that makes the runner fail when
    # optional socksio is not installed.
    host = httpx.Client(base_url=args.base_url, timeout=20, trust_env=False)
    p1 = httpx.Client(base_url=args.base_url, timeout=20, trust_env=False)
    p2 = httpx.Client(base_url=args.base_url, timeout=20, trust_env=False)
    try:
        fixture = run_template(args.base_url)
        logger.event("DM", "api", "创建综合备团模板", response=fixture)
        campaign_id = fixture["campaign"]["id"]
        scene_id = fixture["scene"]["id"]
        character_id = fixture["character"]["id"]
        prefix = f"/campaigns/{campaign_id}"

        second = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/characters",
            json_body={
                "name": "双端验收战士",
                "race": "矮人",
                "background": "士兵",
                "class_name": "战士",
                "level": 1,
                "armor_class": 16,
                "hp": 12,
                "max_hp": 12,
                "speed": 25,
                "ability_scores": {
                    "strength": 16,
                    "dexterity": 12,
                    "constitution": 14,
                    "intelligence": 10,
                    "wisdom": 10,
                    "charisma": 8,
                },
                "actions": [
                    {
                        "name": "长剑",
                        "damage": "1d8+3 挥砍",
                        "range": "5尺",
                        "attack_bonus": 5,
                        "damage_type": "slashing",
                        "cost": "动作",
                        "resolution_kind": "damage",
                    }
                ],
            },
        )
        second_id = second["id"]
        for entity_id, row, col in ((second_id, 5, 5),):
            call(
                host,
                logger,
                "DM",
                "POST",
                f"{prefix}/scenes/{scene_id}/tokens",
                json_body={
                    "entity_type": "character",
                    "entity_id": entity_id,
                    "label": second["name"],
                    "row": row,
                    "col": col,
                    "visible": True,
                },
            )
            call(
                host,
                logger,
                "DM",
                "POST",
                f"{prefix}/scenes/{scene_id}/participants",
                json_body={
                    "entity_type": "character",
                    "entity_id": entity_id,
                    "role": "present",
                    "visible": True,
                },
            )

        for client, actor, display_name in (
            (p1, "玩家一", "艾琳"),
            (p2, "玩家二", "布伦"),
        ):
            call(client, logger, actor, "POST", "/player-room/join", json_body={
                "join_code": fixture["room_code"],
                "display_name": display_name,
            })
        call(p1, logger, "玩家一", "POST", "/player-room/me/bind-character", json_body={"character_id": character_id})
        call(p2, logger, "玩家二", "POST", "/player-room/me/bind-character", json_body={"character_id": second_id})
        call(host, logger, "DM", "POST", f"{prefix}/player-room/live-state", json_body={"scene_id": scene_id})

        scene_state = call(p1, logger, "玩家一", "GET", "/player-room/me")
        call(p2, logger, "玩家二", "GET", "/player-room/me")
        logger.check(
            "两名玩家看到同一 Scene 网格",
            scene_state["table"]["scene"]["grid"]
            == call(p2, logger, "玩家二", "GET", "/player-room/me")["table"]["scene"]["grid"],
        )
        door_id = next(
            item["id"]
            for item in fixture["objects"]
            if "铁门" in item["label"]
        )
        planned = call(
            p1,
            logger,
            "玩家一",
            "POST",
            "/player-room/me/noncombat-actions/plan",
            json_body={
                "action_id": "tool:thieves_tools",
                "target_type": "object",
                "target_id": door_id,
                "message": "我用盗贼工具解除酒窖铁门的锁。",
                "idempotency_key": "three-hour-lockpick-plan",
            },
            expected={201},
        )
        rolled = call(
            p1,
            logger,
            "玩家一",
            "POST",
            f"/player-room/me/noncombat-actions/{planned['id']}/roll",
            json_body={"version": planned["version"], "raw_roll": 10},
        )
        accepted = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/player-action-requests/{planned['id']}/accept",
            json_body={"version": rolled["version"], "dm_note": "锁舌弹开。"},
        )
        logger.check(
            "非战斗撬锁经 DM 确认",
            accepted.get("payload_json", {}).get("phase") == "dm_confirmed",
        )

        combat = call(host, logger, "DM", "POST", f"{prefix}/scenes/{scene_id}/start-combat", json_body={})["combat"]
        combat_id = combat["id"]
        call(host, logger, "DM", "POST", f"{prefix}/player-room/live-state", json_body={"scene_id": scene_id, "combat_id": combat_id})
        combatants = call(host, logger, "DM", "GET", f"{prefix}/combats/{combat_id}/combatants")["items"]
        player_ids = {character_id, second_id}
        logger.check("两名玩家均加入战斗", player_ids <= {item["entity_id"] for item in combatants})

        # Advance a bounded number of turns. Player actions use the LAN API;
        # other turns advance through the DM API so this remains deterministic.
        for turn in range(18):
            snapshot = call(p1, logger, "玩家一", "GET", "/player-room/me")["combat"]
            if not snapshot or snapshot["status"] != "active":
                break
            active = next(item for item in snapshot["combatants"] if item["id"] == snapshot["active_combatant_id"])
            actor_client = p1 if active.get("entity_id") == character_id else p2 if active.get("entity_id") == second_id else host
            actor_name = "玩家一" if actor_client is p1 else "玩家二" if actor_client is p2 else "DM"
            if actor_client is host:
                call(host, logger, actor_name, "POST", f"{prefix}/combats/{combat_id}/turns/advance", json_body={"combat_version": snapshot["version"]})
                continue
            own = next(item for item in snapshot["combatants"] if item["is_own"])
            position = own.get("position") or {"row": 5, "col": 5}
            candidates = [
                (position["row"], position["col"] + 1),
                (position["row"] + 1, position["col"]),
                (position["row"], position["col"] - 1),
            ]
            moved = False
            for row, col in candidates:
                if row < 1 or col < 1:
                    continue
                try:
                    call(actor_client, logger, actor_name, "POST", "/player-room/me/combat/move", json_body={"row": row, "col": col, "combatant_version": own["version"]})
                    moved = True
                    break
                except RuntimeError:
                    continue
            logger.check(f"{actor_name}回合移动或明确拒绝", moved or own["movement_remaining_ft"] == 0, actor=actor_name, surface="combat")
            fresh = call(actor_client, logger, actor_name, "GET", "/player-room/me")["combat"]
            target = next((item for item in fresh["combatants"] if item["entity_type"] == "monster" and item["health_status"] != "倒地"), None)
            if target is None:
                break
            action = "精准长弓" if actor_client is p1 else "长剑"
            call(actor_client, logger, actor_name, "POST", "/player-room/me/combat/attack", json_body={
                "target_combatant_id": target["id"],
                "target_combatant_ids": [target["id"]],
                "action_name": action,
                "attack_total": 20,
                "damage_total": 5,
                "end_turn_after": True,
                "idempotency_key": f"acceptance-{turn}-{actor_name}",
            })

        final = call(p1, logger, "玩家一", "GET", "/player-room/me")
        logger.check("战斗日志存在并可公开同步", bool(final.get("combat", {}).get("log")))
        logger.check("两端玩家角色仍绑定", final.get("character", {}).get("id") == character_id)
        # End the disposable encounter deterministically, then exercise the
        # real settlement and one level-up path rather than mutating SQLite.
        current_combatants = call(
            host, logger, "DM", "GET", f"{prefix}/combats/{combat_id}/combatants"
        )["items"]
        for monster in [item for item in current_combatants if item["entity_type"] == "monster" and item["is_active"]]:
            call(
                host,
                logger,
                "DM",
                "POST",
                f"{prefix}/combats/{combat_id}/actions/confirm",
                json_body={
                    "action_type": "damage",
                    "target_combatant_id": monster["id"],
                    "target_version": monster["version"],
                    "amount": 999,
                    "damage_type": "slashing",
                },
            )
        final_combat_version = final["combat"]["version"]
        ended = call(
            host,
            logger,
            "DM",
            "PATCH",
            f"{prefix}/combats/{combat_id}",
            json_body={"status": "ended"},
            expected={200},
            headers={"If-Match": f'"{final_combat_version}"'},
        )
        ended_version = ended["version"]
        players_in_combat = call(
            host, logger, "DM", "GET", f"{prefix}/combats/{combat_id}/combatants"
        )["items"]
        xp_body = {
            "combat_version": ended_version,
            "resolution_type": "victory",
            "xp_awards": [
                {"character_id": character_id, "xp": 50},
                {"character_id": second_id, "xp": 300},
            ],
            "writebacks": [
                {
                    "combatant_id": item["id"],
                    "character_id": item["entity_id"],
                    "write_hp": True,
                    "write_conditions": True,
                }
                for item in players_in_combat
                if item["entity_type"] == "character" and item["entity_id"] in player_ids
            ],
        }
        settlement = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/combats/{combat_id}/settlement/confirm",
            json_body=xp_body,
        )
        logger.check("战斗结算写入经验", bool(settlement.get("characters")))
        upgraded = call(host, logger, "DM", "GET", f"{prefix}/characters/{second_id}")
        preview = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/characters/{second_id}/advancement/preview",
            json_body={
                "character_version": upgraded["version"],
                "class_name": "战士",
                "hp_mode": "fixed",
            },
        )
        confirmed = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/characters/{second_id}/advancement/confirm",
            json_body={
                "character_version": upgraded["version"],
                "class_name": "战士",
                "hp_mode": "fixed",
                "preview_token": preview["preview_token"],
                "idempotency_key": "three-hour-level-up-1",
            },
        )
        logger.check("战斗奖励后完成一次升级", confirmed.get("to_level") == 2)
        fixture.update({"second_character": {"id": second_id, "name": second["name"]}, "combat": {"id": combat_id}})
        logger.finalize(status="passed" if not logger.failures else "failed", fixture=fixture)
        print(json.dumps({"report_dir": str(args.report_dir), "fixture": fixture}, ensure_ascii=False, indent=2))
        if not args.keep:
            call(host, logger, "DM", "DELETE", f"/campaigns/{campaign_id}", expected={204})
        return 0 if not logger.failures else 1
    except Exception as exc:  # noqa: BLE001 - the report must capture every runner failure
        logger.failure("三端快速流程异常", str(exc))
        logger.finalize(status="failed", fixture=fixture)
        print(f"验收失败，报告目录：{args.report_dir}", file=sys.stderr)
        return 1
    finally:
        host.close()
        p1.close()
        p2.close()


if __name__ == "__main__":
    raise SystemExit(main())
