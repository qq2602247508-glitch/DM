from __future__ import annotations

from pathlib import Path

from dnd_dm_assistant.application.content_ir_workbench import load_records
from dnd_dm_assistant.application.tashas_whole_pack import (
    SOURCE_BOOK,
    build_atoms,
    build_duplicate_version_map,
    build_migration,
    classify_source_record,
    select_source_records,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "data/generated-content/dnd5e_chm/json"


def _records() -> list[dict[str, object]]:
    return select_source_records(load_records(SOURCE_ROOT))


def test_all_tasha_source_records_are_selected_by_book_or_path() -> None:
    records = _records()

    assert len(records) == 144
    assert all(
        record.get("source_book") == SOURCE_BOOK
        or str(record.get("source_relative_path", "")).startswith(f"{SOURCE_BOOK}/")
        for record in records
    )
    assert any(record.get("source_book") == "本书速查" for record in records)


def test_source_record_classification_keeps_indexes_and_dm_material_distinct() -> None:
    by_path = {str(record["source_relative_path"]): record for record in _records()}

    assert classify_source_record(by_path["塔莎的万事坩埚/法术/法术列表.html"])[
        "source_kind"
    ] == "directory"
    assert classify_source_record(by_path["塔莎的万事坩埚/魔法物品/魔法物品列表.html"])[
        "source_kind"
    ] == "directory"
    assert classify_source_record(by_path["塔莎的万事坩埚/城主工具/谜题/四乘四.htm"])[
        "source_kind"
    ] == "puzzle"
    assert classify_source_record(by_path["塔莎的万事坩埚/团队赞助者/君主.html"])[
        "source_kind"
    ] == "narrative"


def test_atomizer_splits_spells_options_items_and_tattoos() -> None:
    atoms = build_atoms(_records())
    kinds = {kind: sum(atom["content_kind"] == kind for atom in atoms) for kind in {
        "spell",
        "feat",
        "maneuver",
        "invocation",
        "infusion",
        "magic_item",
        "magic_tattoo",
        "companion_profile",
    }}

    assert kinds["spell"] == 21
    assert kinds["feat"] >= 15
    assert kinds["maneuver"] >= 6
    assert kinds["invocation"] >= 5
    assert kinds["infusion"] >= 15
    assert kinds["magic_item"] == 36
    assert kinds["magic_tattoo"] == 11
    assert kinds["companion_profile"] == 3


def test_atom_ids_and_fingerprints_are_stable_and_unique() -> None:
    first = build_atoms(_records())
    second = build_atoms(_records())

    assert first == second
    assert len({atom["atom_id"] for atom in first}) == len(first)
    assert all(atom["source_fingerprint"] for atom in first)


def test_migration_statuses_are_exhaustive_and_content_id_funnel_is_exact() -> None:
    migration = build_migration(ROOT)
    atoms = migration["atoms"]

    assert len(atoms) == migration["content_atom_total"]
    assert sum(migration["status_counts"].values()) == len(atoms)
    assert migration["source_record_scanned"] == migration["source_record_total"] == 144
    assert migration["source_record_unclassified"] == 0
    assert migration["content_id_funnel"]["relation_holds"] is True
    # Round XXVIII adds three cleric Domain Spells authored features, so the
    # matched-typed-IR baseline has grown from the earlier 95 to 98.
    assert migration["content_id_funnel"]["matched_typed_ir"] == 98
    assert migration["production_full"] >= 74
    assert migration["dm_assisted"] == 2
    assert migration["game_usable"] >= 76
    assert migration["invalid_source"] == 0


def test_duplicate_map_does_not_deduplicate_by_name_only() -> None:
    migration = build_migration(ROOT)
    duplicate_map = build_duplicate_version_map(migration["atoms"])

    assert duplicate_map["policy"]["rules_variant"]
    assert duplicate_map["policy"]["legacy_variant"]
    assert duplicate_map["map_fingerprint"]
    assert all("relationship" in row for row in duplicate_map["entries"])


def test_item_specs_are_typed_with_fail_closed_effect_boundaries() -> None:
    migration = build_migration(ROOT)

    assert migration["item_ir"]["implemented"] is True
    assert migration["item_ir"]["inventory_atom_count"] == 47
    assert migration["item_ir"]["typed_count"] == 47
    assert migration["item_ir"]["production_count"] == 0
    assert migration["item_spec_catalog"]["item_spec_compile_full"] >= 37
    assert migration["item_ir"]["dm_assisted_count"] == 0
