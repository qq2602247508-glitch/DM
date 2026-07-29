#!/usr/bin/env python3
"""Rehearse the complete one-DM/one-player beginner module through public APIs."""

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
MODULE = REPO / "scripts" / "create-solo-beginner-module.py"


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


def create_module(base_url: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(MODULE), "--rehearsal", "--room-hours", "4"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "DND_DM_ACCEPTANCE_BASE": base_url},
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.getenv("DND_DM_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1"),
    )
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    logger = AcceptanceLogger(args.report_dir, "《暮铃磨坊》1DM+1玩家完整排练", 20260730)
    host = httpx.Client(base_url=args.base_url, timeout=30, trust_env=False)
    player = httpx.Client(base_url=args.base_url, timeout=30, trust_env=False)
    fixture: dict[str, Any] = {}
    campaign_id: str | None = None
    try:
        fixture = create_module(args.base_url)
        campaign_id = fixture["campaign"]["id"]
        character_id = fixture["character"]["id"]
        prefix = f"/campaigns/{campaign_id}"
        scenes = fixture["scenes"]
        logger.event("DM", "module", "创建完整排练副本", response=fixture)

        call(
            player,
            logger,
            "玩家",
            "POST",
            "/player-room/join",
            json_body={"join_code": fixture["room_code"], "display_name": "新手玩家验收"},
        )
        call(
            player,
            logger,
            "玩家",
            "POST",
            "/player-room/me/bind-character",
            json_body={"character_id": character_id},
        )
        first = call(player, logger, "玩家", "GET", "/player-room/me")
        logger.check("玩家绑定预生成角色", first.get("character", {}).get("id") == character_id)
        logger.check(
            "玩家获得完整角色资源",
            len(first.get("character", {}).get("actions", [])) >= 5
            and len(first.get("character", {}).get("spells", [])) >= 2,
        )
        logger.check(
            "玩家看到公开新手手册且看不到DM手册",
            {item["title"] for item in first["table"]["handouts"]}
            == {"新手玩家快速操作卡", "暮铃磨坊委托书"},
        )
        assets = call(
            host,
            logger,
            "DM",
            "GET",
            f"{prefix}/characters/{character_id}/assets",
        )
        logger.check(
            "钱包装备法术资产完整",
            bool(assets.get("wallet"))
            and len(assets.get("equipment", [])) >= 7
            and len(assets.get("spells", [])) >= 6,
        )

        for scene in scenes:
            call(
                host,
                logger,
                "DM",
                "POST",
                f"{prefix}/player-room/live-state",
                json_body={"scene_id": scene["id"], "combat_id": None},
            )
            state = call(player, logger, "玩家", "GET", "/player-room/me")
            grid = state["table"]["scene"]["grid"]
            logger.check(
                f"同步场景网格：{scene['name']}",
                bool(grid) and grid["width"] >= 18 and grid["height"] >= 12,
                surface="scene",
            )
        fourth = call(player, logger, "玩家", "GET", "/player-room/me")
        visible_labels = {
            item["label"] for item in fourth["table"]["scene"].get("objects", [])
        }
        logger.check(
            "战争迷雾隐藏未揭露线索",
            "东侧制动拉杆" not in visible_labels and "违规改造账本" not in visible_labels,
        )

        third_id = scenes[2]["id"]
        call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/player-room/live-state",
            json_body={"scene_id": third_id, "combat_id": None},
        )
        plan = call(
            player,
            logger,
            "玩家",
            "POST",
            "/player-room/me/noncombat-actions/plan",
            json_body={
                "action_id": "tool:thieves_tools",
                "target_type": "object",
                "target_id": fixture["objects"]["cellar_door"],
                "message": "我检查锁芯后用盗贼工具打开地下铁门。",
                "idempotency_key": "duskbell-rehearsal-lockpick",
            },
            expected={201},
        )
        rolled = call(
            player,
            logger,
            "玩家",
            "POST",
            f"/player-room/me/noncombat-actions/{plan['id']}/roll",
            json_body={"version": plan["version"], "raw_roll": 14},
        )
        accepted = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/player-action-requests/{plan['id']}/accept",
            json_body={"version": rolled["version"], "dm_note": "锁芯转开，铁门向内滑动。"},
        )
        logger.check(
            "工具检定经玩家投骰和DM确认推进",
            accepted.get("payload_json", {}).get("phase") == "dm_confirmed",
        )

        fourth_id = scenes[3]["id"]
        call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/player-room/live-state",
            json_body={"scene_id": fourth_id, "combat_id": None},
        )
        combat = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/scenes/{fourth_id}/start-combat",
            json_body={"name": "地下齿轮工坊终局排练"},
        )["combat"]
        combat_id = combat["id"]
        call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/player-room/live-state",
            json_body={"scene_id": fourth_id, "combat_id": combat_id},
        )
        snapshot = call(player, logger, "玩家", "GET", "/player-room/me")["combat"]
        logger.check(
            "玩家自动同步进入同一战斗",
            snapshot["id"] == combat_id and len(snapshot["combatants"]) >= 5,
        )

        # The final map intentionally has separate rooms and total-cover walls.
        # For this bounded rehearsal, move one already-revealed monster into the
        # player's room so the attack assertion tests resolution rather than
        # spending several rounds navigating corridors first.
        dm_combatants = call(
            host,
            logger,
            "DM",
            "GET",
            f"{prefix}/combats/{combat_id}/combatants",
        )["items"]
        own_public = next(item for item in snapshot["combatants"] if item["is_own"])
        own_position = own_public["position"]
        occupied = {
            (
                int(item.get("snapshot_json", {}).get("grid_position", {}).get("row", -1)),
                int(item.get("snapshot_json", {}).get("grid_position", {}).get("col", -1)),
            )
            for item in dm_combatants
        }
        grid_cells = snapshot.get("grid", {}).get("layers_json", {}).get("cells", [])
        blocked = {
            (int(cell["row"]), int(cell["col"]))
            for cell in grid_cells
            if cell.get("kind") == "wall" or cell.get("blocks_sight") is True
        }
        adjacent = next(
            (row, col)
            for row, col in (
                (own_position["row"] - 1, own_position["col"]),
                (own_position["row"], own_position["col"] + 1),
                (own_position["row"] - 1, own_position["col"] + 1),
                (own_position["row"], own_position["col"] - 1),
            )
            if row >= 1
            and col >= 1
            and (row, col) not in occupied
            and (row, col) not in blocked
        )
        rehearsal_target = next(
            item for item in dm_combatants if item["entity_type"] == "monster"
        )
        target_snapshot = dict(rehearsal_target["snapshot_json"])
        target_snapshot["grid_position"] = {"row": adjacent[0], "col": adjacent[1]}
        call(
            host,
            logger,
            "DM",
            "PATCH",
            f"{prefix}/combats/{combat_id}/combatants/{rehearsal_target['id']}",
            json_body={"snapshot_json": target_snapshot},
            headers={"If-Match": f'"{rehearsal_target["version"]}"'},
        )

        player_attacked = False
        for turn in range(12):
            snapshot = call(player, logger, "玩家", "GET", "/player-room/me")["combat"]
            active = next(
                item
                for item in snapshot["combatants"]
                if item["id"] == snapshot["active_combatant_id"]
            )
            if active.get("is_own"):
                target = next(
                    item
                    for item in snapshot["combatants"]
                    if item["id"] == rehearsal_target["id"]
                )
                call(
                    player,
                    logger,
                    "玩家",
                    "POST",
                    "/player-room/me/combat/attack",
                    json_body={
                        "target_combatant_id": target["id"],
                        "target_combatant_ids": [target["id"]],
                        "action_name": "轻弩",
                        "attack_total": 18,
                        "damage_total": 6,
                        "end_turn_after": True,
                        "idempotency_key": "duskbell-player-crossbow",
                    },
                )
                player_attacked = True
                break
            call(
                host,
                logger,
                "DM",
                "POST",
                f"{prefix}/combats/{combat_id}/turns/advance",
                json_body={"combat_version": snapshot["version"]},
            )
        logger.check("玩家端完成一次真实攻击并结束回合", player_attacked)

        combatants = call(
            host,
            logger,
            "DM",
            "GET",
            f"{prefix}/combats/{combat_id}/combatants",
        )["items"]
        for monster in [
            item
            for item in combatants
            if item["entity_type"] == "monster" and item["is_active"]
        ]:
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
                    "damage_type": "force",
                },
            )
        current = call(player, logger, "玩家", "GET", "/player-room/me")["combat"]
        ended = call(
            host,
            logger,
            "DM",
            "PATCH",
            f"{prefix}/combats/{combat_id}",
            json_body={"status": "ended"},
            headers={"If-Match": f'"{current["version"]}"'},
        )
        final_combatants = call(
            host,
            logger,
            "DM",
            "GET",
            f"{prefix}/combats/{combat_id}/combatants",
        )["items"]
        own = next(
            item
            for item in final_combatants
            if item["entity_type"] == "character" and item["entity_id"] == character_id
        )
        settlement = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/combats/{combat_id}/settlement/confirm",
            json_body={
                "combat_version": ended["version"],
                "resolution_type": "victory",
                "xp_awards": [{"character_id": character_id, "xp": 300}],
                "currency_awards": [{"character_id": character_id, "copper": 2_500}],
                "loot_awards": [
                    {
                        "character_id": character_id,
                        "name": "晨溪村英雄徽章",
                        "quantity": 1,
                        "unit_weight_lb": 0.1,
                        "price_cp": 500,
                        "source_label": "custom",
                        "metadata_json": {"module_reward": True},
                    }
                ],
                "writebacks": [
                    {
                        "combatant_id": own["id"],
                        "character_id": character_id,
                        "write_hp": True,
                        "write_conditions": True,
                    }
                ],
                "notes": "排练：战斗、两支线和主线合并结算。",
            },
        )
        logger.check("结算写入经验金币战利品", bool(settlement.get("characters")))

        upgraded = call(host, logger, "DM", "GET", f"{prefix}/characters/{character_id}")
        preview = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/characters/{character_id}/advancement/preview",
            json_body={
                "character_version": upgraded["version"],
                "class_name": "吟游诗人",
                "hp_mode": "fixed",
            },
        )
        confirmed = call(
            host,
            logger,
            "DM",
            "POST",
            f"{prefix}/characters/{character_id}/advancement/confirm",
            json_body={
                "character_version": upgraded["version"],
                "class_name": "吟游诗人",
                "hp_mode": "fixed",
                "preview_token": preview["preview_token"],
                "idempotency_key": "duskbell-level-two-confirm",
            },
        )
        logger.check("300XP后完成吟游诗人1到2级", confirmed.get("to_level") == 2)
        synced = call(player, logger, "玩家", "GET", "/player-room/me")
        logger.check("升级结果同步到玩家端", synced["character"]["level"] == 2)

        logger.finalize(
            status="passed" if not logger.failures else "failed",
            fixture=fixture,
        )
        print(
            json.dumps(
                {"report_dir": str(args.report_dir), "fixture": fixture},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not logger.failures else 1
    except Exception as exc:  # noqa: BLE001 - report every rehearsal failure
        logger.failure("单人新手模组排练异常", str(exc))
        logger.finalize(status="failed", fixture=fixture)
        print(f"排练失败，报告目录：{args.report_dir}", file=sys.stderr)
        return 1
    finally:
        if campaign_id and not args.keep:
            try:
                latest = host.get(f"/campaigns/{campaign_id}")
                if latest.status_code == 200:
                    version = latest.json()["version"]
                    host.delete(
                        f"/campaigns/{campaign_id}",
                        headers={"If-Match": f'"{version}"'},
                    )
            except httpx.HTTPError:
                pass
        host.close()
        player.close()


if __name__ == "__main__":
    raise SystemExit(main())
