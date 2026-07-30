from scripts.duskbell_map_layouts import assert_duskbell_layouts, audit_duskbell_layout


def test_all_duskbell_maps_meet_their_scene_contracts() -> None:
    layouts = assert_duskbell_layouts()

    assert [layout.scene_key for layout in layouts] == [
        "tavern",
        "forest_crossing",
        "mill_yard",
        "gear_undercroft",
        "celebration_tavern",
    ]
    assert all(audit_duskbell_layout(layout) == () for layout in layouts)


def test_forest_crossing_is_outdoor_and_has_three_complete_fallback_routes() -> None:
    forest = assert_duskbell_layouts()[1]
    labels = {str(cell["label"]) for cell in forest.cells}

    assert not any(label.endswith(("北墙", "南墙", "东墙", "西墙")) for label in labels)
    assert {"横卧倒木", "可涉水浅滩", "高地兽径"} <= labels
    assert {int(cell["row"]) for cell in forest.cells if cell["kind"] == "water"} >= {
        1,
        forest.height,
    }


def test_tavern_return_reuses_the_building_but_changes_its_function() -> None:
    opening, celebration = assert_duskbell_layouts()[0], assert_duskbell_layouts()[4]
    opening_structure = {
        (cell["row"], cell["col"], cell["kind"])
        for cell in opening.cells
        if cell["kind"] in {"wall", "door"}
    }
    celebration_structure = {
        (cell["row"], cell["col"], cell["kind"])
        for cell in celebration.cells
        if cell["kind"] in {"wall", "door"}
    }

    assert opening_structure == celebration_structure
    assert any(cell["label"] == "庆功长桌" for cell in celebration.cells)
    assert not any(cell["label"] == "庆功长桌" for cell in opening.cells)
