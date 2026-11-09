"""The calorie, macro and weight maths."""

from datetime import date

import pytest

from custom_components.zp_my_fitness import goals as g


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
