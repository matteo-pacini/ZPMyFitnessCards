// The weight and trends cards' pure functions: units, scales, bands, bars and stats.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain, text } = require("./harness.js");

let fn;
test.before(async () => {
  const ctx = await load();
  fn = vm.runInContext(
    "({ translate, weightUnit, fromKg, toKg, weightText, changeText, weightRange, bandLimits, latestKg, niceStep, ticks, dayScale, linePath, gridHTML, bandOf, rangeStart, weightChartHTML, trendBars, trendStats, trendChartHTML, ringSVG, summaryHTML, summaryFoodHTML, summaryWeightHTML })",
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

test("weights are in lb where Home Assistant's unit system is US customary", () => {
  assert.equal(fn.weightUnit({ config: { unit_system: { mass: "lb" } } }), "lb");
  assert.equal(fn.weightUnit({ config: { unit_system: { mass: "g" } } }), "kg");
  assert.equal(fn.weightUnit({}), "kg");
});

test("weights convert between kg and lb", () => {
  assert.equal(fn.fromKg(0.45359237, "lb"), 1);
  assert.equal(fn.fromKg(70, "kg"), 70);
  // Typed lb are kept to 0.01 kg, which shows as the same 0.1 lb again.
  assert.equal(fn.toKg(150, "lb"), 68.04);
  assert.equal(fn.toKg(69.35, "kg"), 69.35);
  for (let tenths = 441; tenths <= 8818; tenths++) {
    assert.equal(Math.round(fn.fromKg(fn.toKg(tenths / 10, "lb"), "lb") * 10), tenths);
  }
});

test("weights and changes show to 0.1 in their unit and language", () => {
  assert.equal(fn.weightText(68.04, "lb", "en-GB", en()), "150 lb");
  assert.equal(fn.weightText(68.44, "kg", "de", fn.translate("de")), "68,4 kg");
  assert.equal(fn.weightText(70, "kg", "zh-Hans", fn.translate("zh-Hans")), "70 千克");
  assert.equal(fn.changeText(-1.5, "lb", "en-GB", en()), "−3.3 lb");
  assert.equal(fn.changeText(1.24, "kg", "en-GB", en()), "+1.2 kg");
  assert.equal(fn.changeText(0, "kg", "en-GB", en()), "±0 kg");
});

test("the weights a person can log are 20 to 400 kg, rounded inwards in lb", () => {
  assert.deepEqual(plain(fn.weightRange("kg")), [20, 400]);
  assert.deepEqual(plain(fn.weightRange("lb")), [44.1, 881.8]);
});

test("BMI band limits come in the unit shown", () => {
  assert.deepEqual(plain(fn.bandLimits(MATTEO, "kg")), [59.9, 81, 97.2]);
  assert.deepEqual(
    plain(fn.bandLimits(MATTEO, "lb")).map((lb) => lb.toFixed(1)),
    ["132.1", "178.6", "214.3"],
  );
});

test("axis steps are round numbers", () => {
  assert.equal(fn.niceStep(0, 2400, 4), 1000);
  assert.equal(fn.niceStep(78, 92, 4), 5);
  assert.deepEqual(plain(fn.ticks(78, 92, 4)), [80, 85, 90]);
});

test("days are placed in proportion between the first and the last", () => {
  const x = fn.dayScale("2026-11-01", "2026-11-11", 40, 140);
  assert.equal(x("2026-11-01"), 40);
  assert.equal(x("2026-11-06"), 90);
  assert.equal(x("2026-11-11"), 140);
  // A range that starts and ends on the same day does not divide by 0.
  assert.equal(fn.dayScale("2026-11-09", "2026-11-09", 0, 10)("2026-11-09"), 0);
});

test("a line path moves to its first point and draws to the rest, to 0.1", () => {
  assert.equal(fn.linePath([[1, 2.04], [3.25, 4], [5, 6]]), "M1.0,2.0L3.3,4.0L5.0,6.0");
  assert.equal(fn.linePath([]), "");
});

test("grid lines are labelled on the axis", () => {
  const grid = fn.gridHTML([80, 85.5], (v) => 100 - v, "en-GB", 1);
  assert.equal((grid.match(/class="grid"/g) ?? []).length, 2);
  assert.match(grid, /y1="14.5" y2="14.5"\/><text class="axis" x="38" y="18.5" text-anchor="end">85.5</);
  assert.equal(text(fn.gridHTML([1234.5], (v) => v, "en-GB")), "1,235");
});

test("the weight now is the last weigh-in, or the start weight before any", () => {
  assert.equal(fn.latestKg([{ day: "2026-11-02", kg: 88.9 }, { day: "2026-11-09", kg: 88.6 }], MATTEO), 88.6);
  assert.equal(fn.latestKg([], MATTEO), 89);
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
  const svg = fn.weightChartHTML(weights, MATTEO, "2026-08-12", "2026-11-09", "en-GB", en(), "kg");
  const shown = text(svg);
  assert.match(shown, /Healthy/);
  assert.match(shown, /Overweight/);
  assert.doesNotMatch(shown, /Obese|Underweight/);
  assert.match(shown, /Goal 80 kg/);
  assert.equal((svg.match(/class="point"/g) ?? []).length, 3);
  assert.match(svg, /<path class="line" d="M[\d.]+,[\d.]+L/);
});

test("in lb the chart's axis, bands, goal and weigh-ins are in lb", () => {
  const weights = [
    { day: "2026-10-01", kg: 90.1 },
    { day: "2026-11-09", kg: 88.6 },
  ];
  const svg = fn.weightChartHTML(weights, MATTEO, "2026-08-12", "2026-11-09", "en-GB", en(), "lb");
  const shown = text(svg);
  assert.match(shown, /Goal 176\.4 lb/);
  assert.match(svg, /<title>[^<]*: 198\.6 lb<\/title>/);
  assert.match(svg, /<title>[^<]*: 195\.3 lb<\/title>/);
  // The axis runs from 2 kg below the goal to 2 kg above the highest weigh-in,
  // 171 to 204 lb, and the overweight band from 178.6 lb up to its top.
  assert.match(shown, /^Healthy Healthy Overweight Overweight 180 190 200 /);
  const tall = Number(svg.match(/class="band overweight" x="44" y="12" width="544" height="([\d.]+)"/)[1]);
  assert.ok(Math.abs(tall - ((204 - 81 / 0.45359237) / (204 - 171)) * 200) < 1e-9, tall);
});

test("with no weigh-ins the chart still draws the bands and the goal", () => {
  const svg = fn.weightChartHTML([], MATTEO, "2026-08-12", "2026-11-09", "en-GB", en(), "kg");
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
  const shown = text(fn.summaryHTML(day, weights, MATTEO, "2026-10-11", "2026-11-09", "en-GB", en(), "kg"));
  assert.match(shown, /^800 kcal left Protein 60 \/ 100 g Carbs 130 \/ 250 g Fat 35 \/ 60 g 1,200 of 2,000 kcal/);
  assert.match(shown, /Breakfast 500 Lunch 700 Dinner 0 Snacks 0/);
  assert.match(shown, /88\.6 kg Overweight −1\.5 kg in 30 days$/);
});

test("in lb the summary shows the weight and its change in lb", () => {
  const day = { day: "2026-11-09", goals: null, entries: [] };
  const weights = [
    { day: "2026-10-12", kg: 90.1 },
    { day: "2026-11-09", kg: 88.6 },
  ];
  const shown = text(fn.summaryHTML(day, weights, MATTEO, "2026-10-11", "2026-11-09", "en-GB", en(), "lb"));
  assert.match(shown, /195\.3 lb Overweight −3\.3 lb in 30 days$/);
});

test("with no goal yet, the summary shows the calories eaten", () => {
  const day = { day: "2026-11-09", goals: null, entries: [{ meal: "dinner", kcal: 640 }] };
  const shown = text(fn.summaryHTML(day, [], MATTEO, "2026-10-11", "2026-11-09", "en-GB", en(), "kg"));
  assert.match(shown, /^640 kcal Protein 0 g/);
  assert.match(shown, /89 kg Overweight$/);
});

test("the summary's food and weight are drawn apart", () => {
  const day = { day: "2026-11-09", goals: null, entries: [{ meal: "lunch", kcal: 700 }] };
  assert.match(text(fn.summaryFoodHTML(day, "en-GB", en())), /^700 kcal .* Lunch 700 Dinner 0 Snacks 0$/);
  const one = fn.summaryWeightHTML([{ day: "2026-11-09", kg: 88.6 }], MATTEO, "2026-10-11", "2026-11-09", "en-GB", en(), "kg");
  // One weigh-in has no change to show, and no line to draw.
  assert.equal(text(one), "88.6 kg Overweight");
  assert.doesNotMatch(one, /class="spark"/);
});

test("the summary's weight is the last weigh-in, however old; its change and line are the last 30 days'", () => {
  const old = [
    { day: "2026-08-01", kg: 99 },
    { day: "2026-09-01", kg: 98.2 },
  ];
  const shown = fn.summaryWeightHTML(old, MATTEO, "2026-10-11", "2026-11-09", "en-GB", en(), "kg");
  assert.equal(text(shown), "98.2 kg Obese");
  assert.doesNotMatch(shown, /class="spark"/);
  const lately = [...old, { day: "2026-10-20", kg: 96 }, { day: "2026-11-08", kg: 95 }];
  assert.match(text(fn.summaryWeightHTML(lately, MATTEO, "2026-10-11", "2026-11-09", "en-GB", en(), "kg")), /^95 kg Overweight −1 kg in 30 days$/);
});
