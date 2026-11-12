"""Calorie, macro, active calories and weight maths. Pure functions, no Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Multipliers of the resting burn for each activity level.
ACTIVITY = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# Exact, by definition.
KG_PER_LB = 0.45359237
CM_PER_INCH = 2.54

# Weekly change in kg for each pace, fastest first. Metric installs offer the
# kg paces and US customary ones the lb paces, but a person keeps either kind
# when the unit system changes.
PACES = {
    "lose_0_75": -0.75,
    "lose_1_5_lb": -1.5 * KG_PER_LB,
    "lose_0_5": -0.5,
    "lose_1_lb": -1 * KG_PER_LB,
    "lose_0_25": -0.25,
    "lose_0_5_lb": -0.5 * KG_PER_LB,
    "maintain": 0.0,
}

# The usual estimate of the energy in 1 kg of body fat.
KCAL_PER_KG = 7700

KCAL_PER_GRAM = {"protein": 4, "carbs": 4, "fat": 9}

# The units active calories are read in, and how many of each make 1 kcal.
# Withings says "calories" for kcal. Home Assistant's "cal" is the small
# calorie, a thousandth of a kcal, and is not accepted.
PER_KCAL = {"kcal": 1, "calories": 1, "kJ": 4.184}

# Upper limits of the adult BMI bands: below 18.5 underweight, then healthy,
# then overweight from 25, then obese from 30.
BMI_BANDS = (("underweight", 18.5), ("healthy", 25.0), ("overweight", 30.0))


@dataclass(frozen=True)
class Goals:
    """One day's targets."""

    kcal: float
    protein: float
    carbs: float
    fat: float


def age_on(birth: date, day: date) -> int:
    """Whole years from `birth` to `day`."""
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def resting_burn(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    """Estimated kcal burnt a day at rest: Mifflin-St Jeor."""
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == "male" else -161)


def daily_burn(sex: str, weight_kg: float, height_cm: float, age: int, activity: str) -> float:
    """Estimated kcal burnt a day: the resting burn times the activity level."""
    return resting_burn(sex, weight_kg, height_cm, age) * ACTIVITY[activity]


def suggested_calories(burn: float, pace: str) -> float:
    """The daily kcal that changes weight at `pace`."""
    return burn + PACES[pace] * KCAL_PER_KG / 7


def activity_counted(measured: float, share_pct: float, cap: float) -> float:
    """The kcal of a day's measured activity that count.

    That is `share_pct` of `measured`, to the nearest 10 kcal by Python's
    `round`, at most `cap` and never below 0.
    """
    return max(0.0, min(cap, round(measured * share_pct / 100, -1)))


def activity_allowed(resting: float, activity: str) -> float:
    """The kcal of activity the activity level already allows for: 0 for Sedentary."""
    return resting * (ACTIVITY[activity] - ACTIVITY["sedentary"])


def activity_added(counted: float, allowed: float) -> float:
    """The kcal that activity adds to the goal: what counts beyond what is allowed for."""
    return max(0.0, counted - allowed)


def to_kcal(value: float, unit: str | None) -> float | None:
    """`value`, in `unit`, as kcal; None unless `unit` is kcal, "calories" or kJ."""
    per_kcal = PER_KCAL.get(unit)
    return None if per_kcal is None else value / per_kcal


def macro_grams(kcal: float, protein_pct: float, carbs_pct: float, fat_pct: float) -> Goals:
    """Split `kcal` into grams of each macro by percentage of energy."""
    return Goals(
        kcal=kcal,
        protein=kcal * protein_pct / 100 / KCAL_PER_GRAM["protein"],
        carbs=kcal * carbs_pct / 100 / KCAL_PER_GRAM["carbs"],
        fat=kcal * fat_pct / 100 / KCAL_PER_GRAM["fat"],
    )


def band_limits(height_cm: float) -> dict[str, float]:
    """The weights in kg where each BMI band ends, for this height."""
    square = (height_cm / 100) ** 2
    return {
        "underweight_below_kg": round(18.5 * square, 1),
        "overweight_from_kg": round(25.0 * square, 1),
        "obese_from_kg": round(30.0 * square, 1),
    }


def kg_to_lb(kg: float) -> float:
    """`kg` in lb."""
    return kg / KG_PER_LB


def lb_to_kg(lb: float) -> float:
    """`lb` in kg, to 0.01 kg, which is close enough to show the same 0.1 lb again."""
    return round(lb * KG_PER_LB, 2)


def cm_to_feet_inches(cm: float) -> tuple[int, int]:
    """`cm` in feet and whole inches."""
    feet, inches = divmod(round(cm / CM_PER_INCH), 12)
    return feet, inches


def feet_inches_to_cm(feet: float, inches: float) -> float:
    """Feet and inches in cm."""
    return round((feet * 12 + inches) * CM_PER_INCH, 2)


def bmi_band(weight_kg: float, height_cm: float) -> str:
    """The BMI band this weight falls in."""
    bmi = weight_kg / (height_cm / 100) ** 2
    for band, upper in BMI_BANDS:
        if bmi < upper:
            return band
    return "obese"
