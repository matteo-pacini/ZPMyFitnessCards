// Weights are stored, sent and received in kg. On an install whose unit
// system is US customary, the cards show and take them in lb instead.
const KG_PER_LB = 0.45359237;

const weightUnit = (hass) => (hass?.config?.unit_system?.mass === "lb" ? "lb" : "kg");

const fromKg = (kg, unit) => (unit === "lb" ? kg / KG_PER_LB : kg);

// "68.4 kg": a weight in kg, in `unit` to 0.1.
const weightText = (kg, unit, locale, t) => `${number(fromKg(kg, unit), locale, 1)} ${t[unit]}`;

// "+1.2 kg", "−0.5 lb" or "±0 kg": a change of weight in kg, in `unit`.
const changeText = (kg, unit, locale, t) => `${kg > 0 ? "+" : kg < 0 ? "−" : "±"}${weightText(Math.abs(kg), unit, locale, t)}`;

// A person's weight now, in kg: their last weigh-in in `weights`, oldest
// first, or their start weight before there is one.
const latestKg = (weights, person) => (weights.length ? weights[weights.length - 1].kg : person.start_weight_kg);

// The BMI band a weight falls in, from a person's band limits in kg.
function bandOf(kg, person) {
  if (kg < person.underweight_below_kg) return "underweight";
  if (kg < person.overweight_from_kg) return "healthy";
  if (kg < person.obese_from_kg) return "overweight";
  return "obese";
}

// The BMI bands' colours, as a chip's background and a chart band's fill.
const BAND_STYLE = `
  .chip.underweight, .band.underweight { background: var(--info-color, var(--blue-color)); fill: var(--info-color, var(--blue-color)); }
  .chip.healthy, .band.healthy { background: var(--success-color, var(--green-color)); fill: var(--success-color, var(--green-color)); }
  .chip.overweight, .band.overweight { background: var(--warning-color, var(--amber-color)); fill: var(--warning-color, var(--amber-color)); }
  .chip.obese, .band.obese { background: var(--error-color); fill: var(--error-color); }
`;
