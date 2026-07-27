from dnd_dm_assistant.domain.equipment_rules import (
    armor_class_from_profile,
    armor_is_proficient,
    equipment_profile,
)


def test_profiles_use_real_5e_equipment_semantics() -> None:
    assert equipment_profile("镶钉皮甲")["allowed_slots"] == ["armor"]
    assert equipment_profile("盾牌")["allowed_slots"] == ["off_hand"]
    assert equipment_profile("长剑")["allowed_slots"] == ["main_hand", "off_hand"]
    assert equipment_profile("长弓")["two_handed"] is True
    assert equipment_profile("奥术法器")["allowed_slots"] == [
        "focus",
        "main_hand",
        "off_hand",
    ]
    assert equipment_profile("隐形斗篷")["allowed_slots"] == ["worn"]


def test_armor_training_is_tiered() -> None:
    assert armor_is_proficient(["轻甲"], "light") is True
    assert armor_is_proficient(["轻甲"], "medium") is False
    assert armor_is_proficient(["所有护甲"], "heavy") is True
    assert armor_class_from_profile(equipment_profile("皮甲"), 3) == 14
    assert armor_class_from_profile(equipment_profile("鳞甲"), 3) == 16
    assert armor_class_from_profile(equipment_profile("板甲"), 3) == 18
