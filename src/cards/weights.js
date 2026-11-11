// Weights are stored, sent and received in kg. On an install whose unit
// system is US customary, the cards show and take them in lb instead.
const KG_PER_LB = 0.45359237;

const weightUnit = (hass) => (hass?.config?.unit_system?.mass === "lb" ? "lb" : "kg");

const fromKg = (kg, unit) => (unit === "lb" ? kg / KG_PER_LB : kg);

// "68.4 kg": a weight in kg, in `unit` to 0.1.
const weightText = (kg, unit, locale, t) => `${number(fromKg(kg, unit), locale, 1)} ${t[unit]}`;

// "+1.2 kg", "−0.5 lb" or "±0 kg": a change of weight in kg, in `unit`.
const changeText = (kg, unit, locale, t) => `${kg > 0 ? "+" : kg < 0 ? "−" : "±"}${weightText(Math.abs(kg), unit, locale, t)}`;

// The BMI band a weight falls in, from a person's band limits in kg.
function bandOf(kg, person) {
  if (kg < person.underweight_below_kg) return "underweight";
  if (kg < person.overweight_from_kg) return "healthy";
  if (kg < person.obese_from_kg) return "overweight";
  return "obese";
}
