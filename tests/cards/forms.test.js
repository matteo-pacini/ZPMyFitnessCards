// Reading the food form, the cards' editor options and config errors, and
// chart and summary edge cases.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain, text } = require("./harness.js");

let ctx;
let fn;
test.before(async () => {
  ctx = await load();
  fn = vm.runInContext(
    "({ translate, readFoodForm, numberValue, optionList, rangeButtons, weightChartHTML, summaryHTML, shortDate, copyPanelHTML, MEALS })",
    ctx,
  );
});

const en = () => fn.translate("en");

// Just enough of a filled-in food form for readFoodForm.
function form(fields, portions = []) {
  const input = (value) => ({ value: value == null ? "" : String(value) });
  const rows = portions.map(([name, grams]) => ({
    querySelector: (selector) => input(selector.includes("name") ? name : grams),
  }));
  return {
    querySelector: (selector) => input(fields[selector.match(/data-field="(\w+)"/)[1]]),
    querySelectorAll: () => rows,
  };
}

const OATS = { name: " Oats ", barcode: "", kcal: 389, protein: 16.9, carbs: 66, fat: 6.9 };

test("the food form reads numbers, trims text, and leaves blanks empty", () => {
  const { food, error } = fn.readFoodForm(form({ ...OATS, salt: "0.01" }, [["Bowl", 40], ["", ""]]));
  assert.equal(error, null);
  assert.deepEqual(plain(food), {
    name: "Oats",
    barcode: null,
    kcal: 389,
    protein: 16.9,
    carbs: 66,
    fat: 6.9,
    fibre: null,
    sugar: null,
    saturated_fat: null,
    salt: 0.01,
    // The empty row is dropped.
    portions: [{ name: "Bowl", grams: 40 }],
  });
});

test("the food form needs a name and the four main values, none negative", () => {
  for (const fields of [
    { ...OATS, name: "  " },
    { ...OATS, fat: "" },
    { ...OATS, protein: -1 },
    { ...OATS, sugar: -2 },
  ]) {
    assert.equal(fn.readFoodForm(form(fields)).error, "error_required", JSON.stringify(fields));
  }
});

test("each portion needs a name and a weight above 0", () => {
  assert.equal(fn.readFoodForm(form(OATS, [["Bowl", ""]])).error, "error_portion");
  assert.equal(fn.readFoodForm(form(OATS, [["", 40]])).error, "error_portion");
  assert.equal(fn.readFoodForm(form(OATS, [["Bowl", 0]])).error, "error_portion");
});

test("blank number fields are empty, not zero", () => {
  assert.equal(fn.numberValue({ value: " " }), null);
  assert.equal(fn.numberValue(null), null);
  assert.equal(fn.numberValue({ value: "0" }), 0);
});

test("option lists mark the chosen value and escape labels", () => {
  const html = fn.optionList(["a", "b"], { a: "<A>", b: "B" }, "b");
  assert.equal(html, '<option value="a">&lt;A&gt;</option><option value="b" selected>B</option>');
});

test("range buttons mark the chosen range, and there are none without ranges", () => {
  const html = fn.rangeButtons(["7", "30"], "30", en());
  assert.match(html, /data-range="30" aria-pressed="true">30 days/);
  assert.match(html, /data-range="7" aria-pressed="false">7 days/);
  assert.equal(fn.rangeButtons([], "7", en()), "");
});

test("the copy panel offers any past day and every meal", () => {
  const html = fn.copyPanelHTML({ meal: "lunch", fromDay: "2026-11-08", fromMeal: "dinner" }, "2026-11-09", en());
  assert.match(html, /data-field="from_day" type="date" value="2026-11-08" max="2026-11-09"/);
  assert.match(html, /<option value="dinner" selected>Dinner/);
  assert.match(text(html), /^Copy into Lunch from another day/);
});

const PERSON = {
  start_weight_kg: 70,
  start_date: "2026-01-01",
  goal_weight_kg: 62,
  underweight_below_kg: 50.4,
  overweight_from_kg: 68.1,
  obese_from_kg: 81.7,
};

test("long weight histories draw a line without a dot per weigh-in", () => {
  const weights = Array.from({ length: 200 }, (_, i) => ({ day: `2026-${String(1 + Math.floor(i / 28)).padStart(2, "0")}-${String(1 + (i % 28)).padStart(2, "0")}`, kg: 70 - i / 100 }));
  const svg = fn.weightChartHTML(weights, PERSON, "2026-01-01", "2026-08-01", "en-GB", en());
  assert.match(svg, /class="line"/);
  assert.doesNotMatch(svg, /class="point"/);
  // Dates span years only when the range does.
  assert.match(text(svg), /1 Jan/);
});

test("the summary says how far over the goal the day is", () => {
  const day = { day: "2026-11-09", goals: { kcal: 1500, protein: 80, carbs: 180, fat: 50 }, entries: [{ meal: "dinner", kcal: 1800, protein: 90, carbs: 0, fat: 0 }] };
  const html = fn.summaryHTML(day, [], PERSON, "2026-10-11", "2026-11-09", "en-GB", en());
  assert.match(text(html), /^300 kcal over/);
  assert.match(html, /class="ring kcal over"/);
  assert.match(html, /class="ring protein over"/);
});

test("dates show the year only when asked", () => {
  assert.equal(fn.shortDate("2026-11-09", "en-GB"), "9 Nov");
  assert.equal(fn.shortDate("2026-11-09", "en-GB", true), "9 Nov 26");
});

const ELEMENTS = ["metron-food-diary-card", "metron-foods-card", "metron-meals-card", "metron-weight-card", "metron-trends-card", "metron-summary-card", "metron-streak-card"];

test("every card opens the visual editor on its options, which have labels, and has a stub config", () => {
  const options = Object.fromEntries(ELEMENTS.map((name) => [name, plain(ctx.customElements.defined[name].options)]));
  assert.deepEqual(options, {
    "metron-food-diary-card": ["person", "title", "locale"],
    "metron-foods-card": ["title", "locale"],
    "metron-meals-card": ["person", "title", "locale"],
    "metron-weight-card": ["person", "title", "locale"],
    "metron-trends-card": ["person", "title", "locale"],
    "metron-summary-card": ["person", "title", "locale", "navigation_path"],
    "metron-streak-card": ["person", "title", "locale"],
  });
  ctx.document = { createElement: (tag) => ({ tag }) };
  for (const name of ELEMENTS) {
    const Card = ctx.customElements.defined[name];
    for (const option of Card.options) assert.ok(en()[`editor_${option}`], `${name}.${option}`);
    const editor = Card.getConfigElement();
    assert.equal(editor.tag, "metron-card-editor", name);
    assert.equal(editor.options, Card.options, name);
    assert.deepEqual(plain(Card.getStubConfig()), {}, name);
  }
});

test("cards say which option is wrong", () => {
  const Summary = ctx.customElements.defined["metron-summary-card"];
  assert.throws(() => new Summary().setConfig({ navigation_path: 3 }), /navigation_path: must be text/);
  const Weight = ctx.customElements.defined["metron-weight-card"];
  assert.throws(() => new Weight().setConfig({ title: ["x"] }), /title: must be text/);
  assert.throws(() => new Weight().setConfig({ locale: 1 }), /locale: must be text/);
});

test("every card reports a size for the dashboard layout", () => {
  for (const name of ELEMENTS) {
    const size = new ctx.customElements.defined[name]().getCardSize();
    assert.ok(Number.isInteger(size) && size > 0, name);
  }
});
