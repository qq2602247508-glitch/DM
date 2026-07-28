from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.backup_service import BACKUP_TABLE_NAMES
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    AdvancementRecord,
    AdventureSite,
    Attunement,
    Base,
    Campaign,
    Character,
    CharacterCompanion,
    CharacterCondition,
    Clue,
    ClueDiscovery,
    Combat,
    CombatAction,
    Combatant,
    CombatEffect,
    CombatReinforcement,
    CombatSettlement,
    CurrencyTransaction,
    DeathSave,
    DowntimeActivity,
    EncounterAdjustmentProposal,
    EquipmentInstance,
    Event,
    ExplorationTurn,
    FactionReputation,
    Handout,
    KnownSpell,
    Location,
    LocationConnection,
    MonsterInstance,
    NPCMemory,
    OperationTransaction,
    PlayerActionRequest,
    PreparedSpell,
    Quest,
    QuestObjective,
    RegionMap,
    ResourcePool,
    RestRecord,
    RestRecoveryEntry,
    Scene,
    SceneGrid,
    SceneObject,
    SceneParticipant,
    SceneToken,
    ShopInventory,
    SiteConnector,
    SiteLevel,
    SiteRoom,
    StateChangeProposal,
    StoryBeat,
    TravelLeg,
    VisibilityState,
    Wallet,
    WorldClock,
    WorldItem,
)


def _campaign(client: TestClient, name: str) -> dict[str, object]:
    response = client.post("/api/v1/campaigns", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _seed_v2_graph(database_url: str, campaign_id: str) -> None:
    engine = create_engine(database_url)
    with Session(engine) as session, session.begin():
        root = Location(campaign_id=campaign_id, name="雾港", depth=1)
        floor = Location(campaign_id=campaign_id, name="旧宅一层", depth=2)
        room_location = Location(campaign_id=campaign_id, name="锁住的书房", depth=3)
        character = Character(
            campaign_id=campaign_id,
            name="艾琳",
            class_name="Wizard",
            level=1,
            hp=10,
            max_hp=10,
        )
        npc = NPC(
            campaign_id=campaign_id,
            name="管家",
            hp=8,
            max_hp=8,
            location_id=root.id,
        )
        monster = MonsterInstance(
            campaign_id=campaign_id,
            name="影犬",
            hp=12,
            max_hp=12,
        )
        quest = Quest(campaign_id=campaign_id, name="开启书房")
        event = Event(campaign_id=campaign_id, title="钟声响起", location_id=root.id)
        transaction = OperationTransaction(
            campaign_id=campaign_id,
            operation_type="test",
            idempotency_key="backup-v2-operation",
            status="applied",
        )
        session.add_all(
            [
                root,
                floor,
                room_location,
                character,
                npc,
                monster,
                quest,
                event,
                transaction,
            ]
        )
        session.flush()
        floor.parent_location_id = root.id
        room_location.parent_location_id = floor.id

        region = RegionMap(
            campaign_id=campaign_id,
            location_id=root.id,
            name="雾港北区",
            seed=42,
            map_json={"points": [{"location_id": root.id}]},
        )
        scene = Scene(
            campaign_id=campaign_id,
            location_id=floor.id,
            name="旧宅遭遇",
        )
        clue = Clue(
            campaign_id=campaign_id,
            quest_id=quest.id,
            name="烧焦的信",
            source_event_id=event.id,
        )
        rest = RestRecord(
            campaign_id=campaign_id,
            operation_transaction_id=transaction.id,
            rest_type="short",
            status="completed",
            duration_minutes=60,
            idempotency_key="backup-v2-rest",
        )
        session.add_all([region, scene, clue, rest])
        session.flush()

        site = AdventureSite(
            campaign_id=campaign_id,
            region_map_id=region.id,
            location_id=floor.id,
            site_type="building",
            name="普罗宅邸",
            brief="两层旧宅",
            theme="哥特",
            seed=43,
            maximum_levels=1,
            party_level=1,
            party_size=2,
            generation_request_id="backup-v2-site",
        )
        combat = Combat(
            campaign_id=campaign_id,
            scene_id=scene.id,
            name="书房之战",
            status="ended",
            ended_at=datetime.now(UTC),
        )
        pool = ResourcePool(
            campaign_id=campaign_id,
            character_id=character.id,
            key="spell_slot_1",
            label="一环法术位",
            category="spell_slot",
            current=1,
            maximum=2,
            recovery_timing="long_rest",
        )
        known_spell = KnownSpell(
            campaign_id=campaign_id,
            character_id=character.id,
            name="魔法飞弹",
            spell_level=1,
        )
        equipment = EquipmentInstance(
            campaign_id=campaign_id,
            character_id=character.id,
            name="星纹法杖",
            attunement_required=True,
        )
        wallet = Wallet(
            campaign_id=campaign_id,
            character_id=character.id,
            name="钱袋",
            copper=125,
        )
        session.add_all([site, combat, pool, known_spell, equipment, wallet])
        session.flush()

        level = SiteLevel(
            site_id=site.id,
            location_id=floor.id,
            level_index=1,
            name="一层",
            difficulty="low",
            encounter_budget_xp=100,
            reward_budget_gp=25,
            layout_json={"scene_id": scene.id},
        )
        hero = Combatant(
            combat_id=combat.id,
            entity_type="character",
            entity_id=character.id,
            display_name=character.name,
            hp=10,
            max_hp=10,
            snapshot_json={"grid_position": {"row": 2, "col": 2}},
        )
        foe = Combatant(
            combat_id=combat.id,
            entity_type="monster",
            entity_id=monster.id,
            display_name=monster.name,
            hp=0,
            max_hp=12,
            snapshot_json={"grid_position": {"row": 4, "col": 4}},
        )
        session.add_all([level, hero, foe])
        session.flush()

        room = SiteRoom(
            site_level_id=level.id,
            location_id=room_location.id,
            room_index=1,
            name="书房",
            room_type="study",
        )
        action = CombatAction(
            campaign_id=campaign_id,
            combat_id=combat.id,
            actor_combatant_id=hero.id,
            transaction_id=transaction.id,
            action_type="spell",
            target_combatant_ids=[foe.id],
            result_json={"target_id": foe.id},
            round_number=1,
            turn_index=0,
            summary="艾琳施放魔法飞弹",
            idempotency_key="backup-v2-action",
        )
        proposal = EncounterAdjustmentProposal(
            campaign_id=campaign_id,
            scene_id=scene.id,
            combat_id=combat.id,
            source_event_id=event.id,
            operation_transaction_id=transaction.id,
            title="降低难度",
            reason="玩家提前封住侧门",
        )
        session.add_all([room, action, proposal])
        session.flush()

        rows = [
            CharacterCondition(character_id=character.id, condition_name="隐形"),
            LocationConnection(from_location_id=root.id, to_location_id=floor.id),
            SiteConnector(
                site_id=site.id,
                from_level_index=1,
                from_room_index=1,
                to_level_index=1,
                to_room_index=None,
                connector_type="door",
                label="书房门",
            ),
            StoryBeat(campaign_id=campaign_id, title="钟楼真相"),
            QuestObjective(
                campaign_id=campaign_id,
                quest_id=quest.id,
                title="找到书房钥匙",
            ),
            NPCMemory(
                campaign_id=campaign_id,
                npc_id=npc.id,
                summary="玩家没有伤害管家",
            ),
            FactionReputation(
                campaign_id=campaign_id,
                character_id=character.id,
                faction_name="守望者",
                score=2,
            ),
            ClueDiscovery(
                campaign_id=campaign_id,
                clue_id=clue.id,
                discoverer_character_id=character.id,
                method="investigation",
                scene_id=scene.id,
            ),
            DowntimeActivity(
                campaign_id=campaign_id,
                character_id=character.id,
                activity_type="research",
                title="研究烧焦的信",
            ),
            CombatEffect(
                campaign_id=campaign_id,
                combat_id=combat.id,
                target_combatant_id=foe.id,
                source_combatant_id=hero.id,
                source_action_id=action.id,
                name="力场冲击",
                effect_type="damage",
                started_round=1,
            ),
            DeathSave(combatant_id=hero.id, successes=1),
            CombatReinforcement(
                combat_id=combat.id,
                proposal_id=proposal.id,
                entity_type="monster",
                entity_id=monster.id,
                target_round=2,
            ),
            CombatSettlement(
                campaign_id=campaign_id,
                combat_id=combat.id,
                transaction_id=transaction.id,
                resolution_type="victory",
                xp_allocations=[{"character_id": character.id, "xp": 100}],
                writebacks=[{"entity_id": character.id}],
                result_json={"combatant_id": hero.id},
                idempotency_key="backup-v2-settlement",
                confirmed_at=datetime.now(UTC),
            ),
            RestRecoveryEntry(
                rest_record_id=rest.id,
                character_id=character.id,
                resource_pool_id=pool.id,
                recovery_type="spell_slot",
                before_value=1,
                after_value=2,
                amount=1,
                status="applied",
                applied=True,
            ),
            PreparedSpell(known_spell_id=known_spell.id, character_id=character.id),
            Attunement(
                character_id=character.id,
                equipment_instance_id=equipment.id,
            ),
            CurrencyTransaction(
                campaign_id=campaign_id,
                wallet_id=wallet.id,
                amount_copper=25,
                kind="adjustment",
                idempotency_key="backup-v2-currency",
            ),
            ShopInventory(
                campaign_id=campaign_id,
                name="治疗药水",
                quantity=2,
                price_copper=5000,
            ),
            AdvancementRecord(
                campaign_id=campaign_id,
                character_id=character.id,
                operation_transaction_id=transaction.id,
                class_name="Wizard",
                from_level=1,
                to_level=2,
                preview_token="backup-v2-preview",
                idempotency_key="backup-v2-advancement",
            ),
            CharacterCompanion(
                campaign_id=campaign_id,
                owner_character_id=character.id,
                name="灰羽",
                companion_type="familiar",
            ),
            WorldItem(
                campaign_id=campaign_id,
                name="旧钥匙",
                location_id=room_location.id,
            ),
            SceneParticipant(
                scene_id=scene.id,
                entity_type="character",
                entity_id=character.id,
            ),
            SceneGrid(
                scene_id=scene.id,
                width=12,
                height=8,
                layers_json={"source_site_id": site.id},
            ),
            SceneToken(
                scene_id=scene.id,
                entity_type="character",
                entity_id=character.id,
                label=character.name,
                row=2,
                col=2,
            ),
            SceneObject(
                scene_id=scene.id,
                object_type="door",
                label="书房门",
                row=3,
                col=3,
                interaction_json={"location_id": room_location.id},
            ),
            VisibilityState(
                scene_id=scene.id,
                viewer_key=f"character:{character.id}",
                explored_cells=[{"row": 2, "col": 2}],
            ),
            Handout(
                campaign_id=campaign_id,
                title="烧焦的信",
                body="不要相信钟楼。",
                published=True,
            ),
            PlayerActionRequest(
                campaign_id=campaign_id,
                character_id=character.id,
                player_key="player-1",
                action_type="skill",
                payload_json={"target_id": npc.id},
                character_version=1,
                idempotency_key="backup-v2-player-action",
            ),
            WorldClock(campaign_id=campaign_id, current_time=datetime.now(UTC)),
            ExplorationTurn(
                campaign_id=campaign_id,
                scene_id=scene.id,
                transaction_id=transaction.id,
                minutes=10,
            ),
            TravelLeg(
                campaign_id=campaign_id,
                from_location_id=root.id,
                to_location_id=floor.id,
                transaction_id=transaction.id,
                distance_miles=1,
                duration_minutes=30,
            ),
            StateChangeProposal(
                campaign_id=campaign_id,
                operation="update",
                entity_type="npc",
                entity_id=npc.id,
                reason="管家改变态度",
                created_by_model="test-model",
                request_id="backup-v2-proposal",
            ),
        ]
        session.add_all(rows)
        campaign = session.get(Campaign, campaign_id)
        assert campaign is not None
        campaign.current_location_id = floor.id


def test_campaign_backup_v2_round_trips_authoritative_graph(
    campaign_client: TestClient,
) -> None:
    source = _campaign(campaign_client, "完整备份")
    database_url = str(campaign_client.database_url)  # type: ignore[attr-defined]
    _seed_v2_graph(database_url, str(source["id"]))

    exported_response = campaign_client.get(
        f"/api/v1/campaigns/{source['id']}/export"
    )
    assert exported_response.status_code == 200
    exported = exported_response.json()
    assert exported["schema_version"] == "2.0"
    assert set(exported["tables"]) == set(BACKUP_TABLE_NAMES)
    assert exported["manifest"]["record_count"] == sum(exported["counts"].values())
    assert len(exported["manifest"]["sha256"]) == 64
    for table_name in (
        "region_maps",
        "adventure_sites",
        "site_levels",
        "site_rooms",
        "site_connectors",
        "scene_grids",
        "scene_tokens",
        "scene_objects",
        "known_spells",
        "prepared_spells",
        "equipment_instances",
        "attunements",
        "resource_pools",
        "wallets",
        "currency_transactions",
        "advancement_records",
        "story_beats",
        "player_action_requests",
        "combat_settlements",
    ):
        assert exported["counts"][table_name] == 1

    imported_response = campaign_client.post(
        "/api/v1/campaigns/import-backup",
        json={"backup": exported, "name": "完整备份副本"},
    )
    assert imported_response.status_code == 201, imported_response.text
    imported_id = imported_response.json()["id"]
    imported_export = campaign_client.get(
        f"/api/v1/campaigns/{imported_id}/export"
    ).json()
    assert imported_export["counts"] == exported["counts"]

    models = {
        mapper.class_.__table__.name: mapper.class_
        for mapper in Base.registry.mappers
        if mapper.local_table is not None
    }
    engine = create_engine(database_url)
    with Session(engine) as session:
        imported_counts: dict[str, int] = {}
        for table_name in BACKUP_TABLE_NAMES:
            model = models[table_name]
            if "campaign_id" in model.__table__.c:
                imported_counts[table_name] = int(
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.__table__.c.campaign_id == imported_id)
                    )
                    or 0
                )
        assert {
            table: imported_counts[table]
            for table in imported_counts
        } == {
            table: exported["counts"][table]
            for table in imported_counts
        }
        imported_campaign = session.get(Campaign, imported_id)
        assert imported_campaign is not None
        assert imported_campaign.current_location_id is not None
        assert imported_campaign.current_location_id != exported["campaign"]["current_location_id"]
        imported_current_location = session.get(
            Location, imported_campaign.current_location_id
        )
        assert imported_current_location is not None
        assert imported_current_location.name == "旧宅一层"
        imported_action = session.scalar(
            select(CombatAction).where(CombatAction.campaign_id == imported_id)
        )
        assert imported_action is not None
        source_combatant_ids = {
            row["id"] for row in exported["tables"]["combatants"]
        }
        assert source_combatant_ids.isdisjoint(imported_action.target_combatant_ids)
        imported_settlement = session.scalar(
            select(CombatSettlement).where(CombatSettlement.campaign_id == imported_id)
        )
        assert imported_settlement is not None
        imported_result = json.dumps(imported_settlement.result_json)
        assert all(source_id not in imported_result for source_id in source_combatant_ids)
        imported_visibility = session.scalar(
            select(VisibilityState).join(Scene).where(Scene.campaign_id == imported_id)
        )
        assert imported_visibility is not None
        source_character_id = exported["tables"]["characters"][0]["id"]
        assert source_character_id not in imported_visibility.viewer_key


def test_campaign_backup_v2_rejects_tampered_payload(
    campaign_client: TestClient,
) -> None:
    campaign = _campaign(campaign_client, "校验备份")
    exported = campaign_client.get(
        f"/api/v1/campaigns/{campaign['id']}/export"
    ).json()
    exported["campaign"]["description"] = "被篡改"
    response = campaign_client.post(
        "/api/v1/campaigns/import-backup",
        json={"backup": exported},
    )
    assert response.status_code == 400
    assert "checksum" in response.text


def test_campaign_backup_v1_remains_importable(campaign_client: TestClient) -> None:
    response = campaign_client.post(
        "/api/v1/campaigns/import-backup",
        json={
            "backup": {
                "schema_version": "1.0",
                "exported_at": datetime.now(UTC).isoformat(),
                "campaign": {"name": "旧格式", "version": 1},
                "characters": [
                    {
                        "id": "legacy-character",
                        "name": "旧角色",
                        "hp": 6,
                        "max_hp": 6,
                        "version": 1,
                    }
                ],
            }
        },
    )
    assert response.status_code == 201, response.text
    imported_id = response.json()["id"]
    characters = campaign_client.get(
        f"/api/v1/campaigns/{imported_id}/characters"
    ).json()["items"]
    assert [row["name"] for row in characters] == ["旧角色"]
