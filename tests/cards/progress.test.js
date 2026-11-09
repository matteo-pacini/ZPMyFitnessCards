// The weight and trends cards' pure functions: scales, bands, bars and stats.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain, text } = require("./harness.js");

let fn;
test.before(async () => {
  const ctx = await load("fitness-cards.js");
  fn = vm.runInContext(
    "({ translate, niceStep, ticks, bandOf, rangeStart, weightChartHTML, trendBars, trendStats, trendChartHTML, ringSVG, summaryHTML })",
    ctx,
  );
});

const en = () => fn.translate("en");

const MATTEO = {
  id: "m",
  name: "Matteo",
  start_weight_kg: 89,
  start_date: "2026-11-01",
  goal_weight_kg: 80,
  underweight_below_kg: 59.9,
  overweight_from_kg: 81,
  obese_from_kg: 97.2,
};

test("axis steps are round numbers", () => {
  assert.equal(fn.niceStep(0, 2400, 4), 1000);
  assert.equal(fn.niceStep(78, 92, 4), 5);
  assert.deepEqual(plain(fn.ticks(78, 92, 4)), [80, 85, 90]);
});

test("a weight's BMI band comes from the person's limits", () => {
  assert.equal(fn.bandOf(59.8, MATTEO), "underweight");
  assert.equal(fn.bandOf(80.9, MATTEO), "healthy");
  assert.equal(fn.bandOf(81, MATTEO), "overweight");
  assert.equal(fn.bandOf(97.2, MATTEO), "obese");
});

test("ranges end today; all of it starts at the first weigh-in", () => {
  assert.equal(fn.rangeStart("90", "2026-11-09"), "2026-08-12");
  assert.equal(fn.rangeStart("all", "2026-11-09", "2017-05-31"), "2017-05-31");
  assert.equal(fn.rangeStart("all", "2026-11-09", "2026-11-09"), "2026-10-11");
});

test("the weight chart shows the bands in view, the goal and each weigh-in", () => {
  const weights = [
    { day: "2026-09-01", kg: 92.4 },
    { day: "2026-10-01", kg: 90.1 },
    { day: "2026-11-09", kg: 88.6 },
  ];
  const svg = fn.weightChartHTML(weights, MATTEO, "2026-08-12", "2026-11-09", "en-GB", en());
  const shown = text(svg);
  assert.match(shown, /Healthy/);
  assert.match(shown, /Overweight/);
  assert.doesNotMatch(shown, /Obese|Underweight/);
  assert.match(shown, /Goal 80 kg/);
  assert.equal((svg.match(/class="point"/g) ?? []).length, 3);
  assert.match(svg, /<path class="line" d="M[\d.]+,[\d.]+L/);
});

test("with no weigh-ins the chart still draws the bands and the goal", () => {
  const svg = fn.weightChartHTML([], MATTEO, "2026-08-12", "2026-11-09", "en-GB", en());
  assert.doesNotMatch(svg, /class="line"/);
  assert.match(text(svg), /Goal 80 kg/);
});

const day = (date, kcal, goal = 2000, protein = 0) => ({
  day: date,
  meals: kcal ? { lunch: { kcal, protein, carbs: 0, fat: 0 } } : {},
  goals: goal ? { kcal: goal } : null,
});

test("daily bars stack meals and carry each day's goal", () => {
  const bars = plain(fn.trendBars([day("2026-11-08", 1800), day("2026-11-09", 0, 1900)], false));
  assert.deepEqual(bars[0].meals, [0, 1800, 0, 0]);
  assert.equal(bars[1].goal, 1900);
  assert.equal(bars[1].logged, false);
});

test("weekly bars average the logged days, newest week full", () => {
  const days = Array.from({ length: 10 }, (_, i) => day(`2026-11-${String(i + 1).padStart(2, "0")}`, i % 2 ? 2000 : 0, 1800));
  const bars = plain(fn.trendBars(days, true));
  assert.equal(bars.length, 2);
  assert.deepEqual(bars[1].days, ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10"]);
  // Days 4, 6, 8 and 10 are logged, each 2000.
  assert.equal(bars[1].meals[1], 2000);
  assert.equal(bars[1].goal, 1800);
});

test("stats count only logged days before today", () => {
  const days = [day("2026-11-06", 1500, 2000, 100), day("2026-11-07", 2500, 2000, 0), day("2026-11-08", 0), day("2026-11-09", 300)];
  const stats = plain(fn.trendStats(days, "2026-11-09"));
  assert.equal(stats.logged, 2);
  assert.equal(stats.average, 2000);
  assert.equal(stats.onGoal, 1);
  assert.equal(stats.withGoal, 2);
  assert.equal(stats.split.protein, 100);
});

test("daily bars can be tapped to open the day; weekly ones cannot", () => {
  const bars = fn.trendBars([day("2026-11-08", 1800), day("2026-11-09", 1200)], false);
  const daily = fn.trendChartHTML(bars, false, "en-GB", en());
  assert.equal((daily.match(/data-action="open-day"/g) ?? []).length, 2);
  assert.match(daily, /data-day="2026-11-09"/);
  const weekly = fn.trendChartHTML(bars, true, "en-GB", en());
  assert.doesNotMatch(weekly, /open-day/);
});

test("rings fill by share of the goal and turn red past it", () => {
  const full = 2 * Math.PI * ((36 - 5) / 2);
  const half = fn.ringSVG(36, 5, 0.5, "protein");
  assert.match(half, new RegExp(`stroke-dasharray="${(full / 2).toFixed(2)} ${full.toFixed(2)}"`));
  const over = fn.ringSVG(36, 5, 1.4, "fat");
  assert.match(over, /class="ring fat over"/);
  assert.match(over, new RegExp(`stroke-dasharray="${full.toFixed(2)} `));
});

test("the summary shows what is left, the macros, the meals and the weight", () => {
  const day = {
    day: "2026-11-09",
    goals: { kcal: 2000, protein: 100, carbs: 250, fat: 60 },
    entries: [
      { meal: "breakfast", kcal: 500, protein: 20, carbs: 60, fat: 15 },
      { meal: "lunch", kcal: 700, protein: 40, carbs: 70, fat: 20 },
    ],
  };
  const weights = [
    { day: "2026-10-12", kg: 90.1 },
    { day: "2026-11-09", kg: 88.6 },
  ];
  const shown = text(fn.summaryHTML(day, weights, MATTEO, "2026-10-11", "2026-11-09", "en-GB", en()));
  assert.match(shown, /^800 kcal left Protein 60 \/ 100 g Carbs 130 \/ 250 g Fat 35 \/ 60 g 1,200 of 2,000 kcal/);
  assert.match(shown, /Breakfast 500 Lunch 700 Dinner 0 Snacks 0/);
  assert.match(shown, /88\.6 kg Overweight −1\.5 kg in 30 days$/);
});

test("with no goal yet, the summary shows the calories eaten", () => {
  const day = { day: "2026-11-09", goals: null, entries: [{ meal: "dinner", kcal: 640 }] };
  const shown = text(fn.summaryHTML(day, [], MATTEO, "2026-10-11", "2026-11-09", "en-GB", en()));
  assert.match(shown, /^640 kcal Protein 0 g/);
  assert.match(shown, /89 kg Overweight$/);
});
