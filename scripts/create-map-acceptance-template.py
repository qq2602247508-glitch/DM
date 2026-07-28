#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any

import httpx

BASE = os.getenv("DND_DM_ACCEPTANCE_BASE", "http://127.0.0.1:8000/api/v1")


def site(client: httpx.Client, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    preview = client.post(
        f"{BASE}/campaigns/{campaign_id}/sites/generate/preview", json=payload
    )
    preview.raise_for_status()
    confirmed = client.post(
        f"{BASE}/campaigns/{campaign_id}/sites/generate/confirm",
        headers={"X-Request-ID": f"map-acceptance-{payload['seed']}"},
        json={"preview": preview.json()},
    )
    confirmed.raise_for_status()
    return confirmed.json()


def main() -> None:
    with httpx.Client(timeout=30, trust_env=False) as client:
        campaign = client.post(
            f"{BASE}/campaigns",
            json={
                "name": "区域建筑与地下城综合验收团",
                "description": "用于验证区域地图、建筑楼层、地下城曲线和共享战斗网格。",
                "ruleset": "dnd5e",
                "primary_rules_year": 2024,
            },
        )
        campaign.raise_for_status()
        campaign_id = campaign.json()["id"]
        mansion = site(
            client,
            campaign_id,
            {
                "site_type": "building",
                "name": "普罗宅邸",
                "brief": "海区旧贵族宅邸，包含会客厅、卧室、书房、储藏室和隐蔽地下室。",
                "region_path": "深水城/海区",
                "maximum_levels": 3,
                "rooms_min": 5,
                "rooms_max": 8,
                "party_level": 5,
                "party_size": 4,
                "starting_difficulty": "low",
                "difficulty_growth": 1,
                "monster_density": 45,
                "reward_rate": 1,
                "seed": 202407281,
            },
        )
        dungeon = site(
            client,
            campaign_id,
            {
                "site_type": "dungeon",
                "name": "低语矿坑",
                "brief": "被夺心魔实验污染的废弃矿坑，潮湿幽暗，越深入心灵威胁越强。",
                "region_path": "深水城/海区",
                "maximum_levels": 5,
                "rooms_min": 4,
                "rooms_max": 9,
                "party_level": 5,
                "party_size": 4,
                "starting_difficulty": "low",
                "difficulty_growth": 2,
                "monster_density": 80,
                "reward_rate": 1.2,
                "seed": 202407282,
            },
        )
        print(
            {
                "campaign_id": campaign_id,
                "campaign_name": campaign.json()["name"],
                "building_id": mansion["id"],
                "dungeon_id": dungeon["id"],
                "building_levels": len(mansion["levels"]),
                "dungeon_levels": len(dungeon["levels"]),
            }
        )


if __name__ == "__main__":
    main()
