"""The calorie, macro and weight maths."""

from datetime import date

import pytest

from custom_components.metron import goals as g
from custom_components.metron.const import MAX_KG, MAX_LB, MIN_KG, MIN_LB


def test_age_counts_whole_years() -> None:
    assert g.age_on(date(1996, 3, 15), date(2026, 3, 14)) == 29
    assert g.age_on(date(1996, 3, 15), date(2026, 3, 15)) == 30


def test_daily_burn_is_mifflin_st_jeor_times_activity() -> None:
    # 10 * 70 + 6.25 * 165 - 5 * 30 - 161 = 1420.25, times 1.55.
    assert g.daily_burn("female", 70, 165, 30, "moderate") == pytest.approx(2201.3875)
    # 10 * 89 + 6.25 * 180 - 5 * 36 + 5 = 1840, times 1.375.
    assert g.daily_burn("male", 89, 180, 36, "light") == pytest.approx(2530)


def test_pace_takes_7700_kcal_per_kg_a_week() -> None:
    assert g.suggested_calories(2200, "lose_0_5") == pytest.approx(1650)
    assert g.suggested_calories(2200, "maintain") == 2200


def test_macros_split_energy_into_grams() -> None:
    goals = g.macro_grams(2000, 20, 50, 30)
    assert goals == g.Goals(kcal=2000, protein=100, carbs=250, fat=pytest.approx(66.67, 0.01))


def test_band_limits_follow_height() -> None:
    assert g.band_limits(180) == {
        "underweight_below_kg": 59.9,
        "overweight_from_kg": 81.0,
        "obese_from_kg": 97.2,
    }


@pytest.mark.parametrize(
    ("kg", "band"),
    [
        (59.8, "underweight"),
        (60.0, "healthy"),
        (80.9, "healthy"),
        (81.0, "overweight"),
        (97.2, "obese"),
    ],
)
def test_bmi_band(kg: float, band: str) -> None:
    assert g.bmi_band(kg, 180) == band


def test_converts_kg_to_lb_and_cm_to_feet_and_inches() -> None:
    assert g.kg_to_lb(0.45359237) == 1
    assert g.kg_to_lb(70) == pytest.approx(154.32, abs=0.005)
    # To 0.01 kg.
    assert g.lb_to_kg(150) == 68.04
    assert g.cm_to_feet_inches(165) == (5, 5)
    assert g.cm_to_feet_inches(182.8) == (6, 0)
    assert g.feet_inches_to_cm(5, 9) == 175.26


def test_every_weight_in_lb_comes_back_the_same() -> None:
    for tenths in range(441, 8819):
        assert round(g.kg_to_lb(g.lb_to_kg(tenths / 10)), 1) == tenths / 10


def test_the_lb_limits_are_the_kg_limits_rounded_inwards() -> None:
    assert g.lb_to_kg(MIN_LB - 0.1) < MIN_KG <= g.lb_to_kg(MIN_LB)
    assert g.lb_to_kg(MAX_LB) <= MAX_KG < g.lb_to_kg(MAX_LB + 0.1)


def test_paces_in_lb_are_kept_in_kg_fastest_first() -> None:
    assert g.PACES["lose_1_lb"] == -0.45359237
    assert g.suggested_calories(2200, "lose_1_lb") == pytest.approx(2200 - 0.45359237 * 1100)
    assert list(g.PACES.values()) == sorted(g.PACES.values())


# Active calories. Anna: female, 35, 165 cm, 70 kg.
ANNA = ("female", 70, 165, 35)


def test_resting_burn_is_mifflin_st_jeor() -> None:
    # 10 * 70 + 6.25 * 165 - 5 * 35 - 161.
    assert g.resting_burn(*ANNA) == 1395.25
    # 10 * 89 + 6.25 * 180 - 5 * 36 + 5.
    assert g.resting_burn("male", 89, 180, 36) == 1840


@pytest.mark.parametrize("activity", list(g.ACTIVITY))
@pytest.mark.parametrize("sex", ["female", "male"])
def test_daily_burn_is_unchanged_at_every_level(sex: str, activity: str) -> None:
    def before(sex: str, weight_kg: float, height_cm: float, age: int, activity: str) -> float:
        resting = 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == "male" else -161)
        return resting * g.ACTIVITY[activity]

    assert g.daily_burn(sex, 70.3, 165.1, 35, activity) == before(sex, 70.3, 165.1, 35, activity)


@pytest.mark.parametrize(
    ("measured", "share", "counted"),
    [
        # E5: 3,790 kJ is 905.8 kcal, so 75% is 679.4: 68 tens.
        (905.8, 75, 680),
        (906, 75, 680),
        (120, 75, 90),
        # Python's round: a half ten goes to the even ten.
        (900, 75, 680),
        (220, 75, 160),
        (906, 100, 910),
        (906, 0, 0),
        (0, 75, 0),
        (-200, 75, 0),
    ],
)
def test_activity_counted_is_the_share_to_the_nearest_10(
    measured: float, share: float, counted: float
) -> None:
    assert g.activity_counted(measured, share, 1500) == counted


def test_activity_counted_stops_at_the_cap() -> None:
    # E4: 75% of 2,400 is 1,800.
    assert g.activity_counted(2400, 75, 1500) == 1500
    assert g.activity_counted(2000, 75, 1500) == 1500
    assert g.activity_counted(1990, 75, 1500) == 1490
    assert g.activity_counted(2400, 75, 100) == 100


@pytest.mark.parametrize(
    ("activity", "allowed"),
    [
        ("sedentary", 0),
        ("light", 1395.25 * 0.175),
        ("moderate", 1395.25 * 0.35),
        ("active", 1395.25 * 0.525),
        ("very_active", 1395.25 * 0.7),
    ],
)
def test_activity_allowed_is_what_the_level_adds_to_sedentary(
    activity: str, allowed: float
) -> None:
    assert g.activity_allowed(g.resting_burn(*ANNA), activity) == pytest.approx(allowed)


def test_activity_added_is_what_counts_beyond_the_level() -> None:
    allowed = g.activity_allowed(1395.25, "light")
    assert allowed == pytest.approx(244.17, abs=0.005)
    assert g.activity_added(120, allowed) == 0
    assert g.activity_added(allowed, allowed) == 0
    assert g.activity_added(680, allowed) == pytest.approx(435.83, abs=0.005)
    assert g.activity_added(90, 0) == 90
    assert g.activity_added(0, 0) == 0


@pytest.mark.parametrize(
    ("value", "unit", "kcal"),
    [
        (906, "kcal", 906),
        (906, "calories", 906),
        # E5.
        (3790, "kJ", pytest.approx(905.8, abs=0.05)),
        (4184, "kJ", pytest.approx(1000)),
        # E6: the most a day can measure.
        (41840, "kJ", pytest.approx(10000)),
        (0, "kJ", 0),
        (906, "cal", None),
        (906, "Wh", None),
        (906, "kWh", None),
        (906, "W", None),
        (906, "steps", None),
        (906, "%", None),
        (906, "KCAL", None),
        (906, None, None),
    ],
)
def test_to_kcal_reads_kcal_calories_and_kj(value: float, unit: str | None, kcal: object) -> None:
    assert g.to_kcal(value, unit) == kcal
