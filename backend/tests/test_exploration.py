from dnd_dm_assistant.domain.exploration import cover_between, grid_distance_ft, line_of_sight, movement_cost_ft, travel_minutes


def test_geometry_and_difficult_path() -> None:
    assert grid_distance_ft((1, 1), (3, 2)) == 10
    assert movement_cost_ft([(1, 1), (1, 2), (2, 2)], {(1, 2)}) == 15


def test_los_and_cover() -> None:
    assert not line_of_sight((1, 1), (4, 1), {(2, 1)})
    assert cover_between((1, 1), (4, 1), set(), {(2, 1)}) == "total"
    assert cover_between((1, 1), (4, 1), {(4, 2)}, set()) == "half"


def test_travel_paces() -> None:
    assert travel_minutes(3, "normal") == 60
    assert travel_minutes(1, "slow") == 30
