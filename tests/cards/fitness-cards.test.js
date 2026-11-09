const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain, text } = require("./harness.js");

let ctx;
let fn;
test.before(async () => {
  ctx = await load("fitness-cards.js");
  fn = vm.runInContext(
    "({ STRINGS, translate, todayIn, shiftDay, dayLabel, scaled, totals, findPerson, diaryBodyHTML, previewHTML, foodsListHTML, foodFormHTML, editPanelHTML, addPanelHTML })",
    ctx,
  );
});

const en = () => fn.translate("en");

test("today is the date in Home Assistant's time zone", () => {
  const late = new Date("2026-11-09T23:30:00Z");
  assert.equal(fn.todayIn("Europe/London", late), "2026-11-09");
  assert.equal(fn.todayIn("Europe/Rome", late), "2026-11-10");
  assert.equal(fn.todayIn("America/New_York", late), "2026-11-09");
});

test("days move across months, years and leap days", () => {
  assert.equal(fn.shiftDay("2026-03-01", -1), "2026-02-28");
  assert.equal(fn.shiftDay("2028-03-01", -1), "2028-02-29");
  assert.equal(fn.shiftDay("2026-12-31", 1), "2027-01-01");
});

test("day labels say today and yesterday, then the date", () => {
  const t = en();
  assert.equal(fn.dayLabel("2026-11-09", "2026-11-09", "en-GB", t), "Today");
  assert.equal(fn.dayLabel("2026-11-08", "2026-11-09", "en-GB", t), "Yesterday");
  assert.equal(fn.dayLabel("2026-11-02", "2026-11-09", "en-GB", t), "Mon 2 Nov");
  assert.equal(fn.dayLabel("2025-11-02", "2026-11-09", "en-GB", t), "Sun, 2 Nov 2025");
});

test("foods scale from per 100 g, keeping missing values missing", () => {
  const oats = { kcal: 389, protein: 16.9, carbs: 66, fat: 6.9, fibre: 10, sugar: null, saturated_fat: null, salt: null };
  const portion = plain(fn.scaled(oats, 60));
  assert.equal(portion.kcal, 233.4);
  assert.equal(portion.fibre, 6);
  assert.equal(portion.sugar, null);
});

test("totals count missing values as 0", () => {
  const sums = plain(fn.totals([{ kcal: 100, protein: 5 }, { kcal: 50, protein: null }]));
  assert.equal(sums.kcal, 150);
  assert.equal(sums.protein, 5);
  assert.equal(sums.salt, 0);
});

test("the card finds its person by name, or by the logged-in user", () => {
  const people = [
    { id: "a", name: "Debora", person_entity: "person.debora" },
    { id: "b", name: "Matteo", person_entity: "person.matteo" },
  ];
  const hass = {
    user: { id: "u2" },
    states: {
      "person.debora": { entity_id: "person.debora", attributes: { user_id: "u1" } },
      "person.matteo": { entity_id: "person.matteo", attributes: { user_id: "u2" } },
    },
  };
  assert.equal(fn.findPerson(people, { person: " debora " }, hass).id, "a");
  assert.equal(fn.findPerson(people, {}, hass).id, "b");
  assert.equal(fn.findPerson(people, { person: "Nora" }, hass), null);
  assert.equal(fn.findPerson(people, {}, { ...hass, user: { id: "u9" } }), null);
});

const DAY = {
  day: "2026-11-09",
  goals: { kcal: 2000, protein: 100, carbs: 250, fat: 60 },
  weight_kg: null,
  entries: [
    { id: 1, meal: "breakfast", name: "Porridge oats", grams: 60, kcal: 233.4, protein: 10.1, carbs: 39.6, fat: 4.1 },
    { id: 2, meal: "dinner", name: "Pizza <large>", grams: null, kcal: 900, protein: 30, carbs: 100, fat: 70 },
  ],
};

test("the diary sums the day against its goal, meal by meal", () => {
  const shown = text(fn.diaryBodyHTML(DAY, en(), "en-GB"));
  assert.match(shown, /^2,000 Goal − 1,133 Food = 867 Remaining/);
  assert.match(shown, /Protein 40 \/ 100 g Carbs 140 \/ 250 g Fat 74 \/ 60 g/);
  assert.match(shown, /Breakfast 233 kcal Porridge oats 60 g 233 \+ Add food Copy/);
  assert.match(shown, /Lunch Nothing logged yet \+ Add food/);
  assert.match(shown, /Dinner 900 kcal Pizza <large> 900/);
  // Fat is over its goal.
  assert.match(fn.diaryBodyHTML(DAY, en(), "en-GB"), /class="macro fat over"/);
});

test("the diary shows what is over the goal, and copes with no goal", () => {
  const over = { ...DAY, goals: { kcal: 1000, protein: 1, carbs: 1, fat: 1 } };
  assert.match(text(fn.diaryBodyHTML(over, en(), "en-GB")), /= 133 Over/);
  const none = text(fn.diaryBodyHTML({ ...DAY, goals: null }, en(), "en-GB"));
  assert.match(none, /^1,133 Food Breakfast/);
});

test("the diary follows the language for words and numbers", () => {
  const shown = text(fn.diaryBodyHTML(DAY, fn.translate("de"), "de"));
  assert.match(shown, /^2\.000 Ziel − 1\.133 Essen = 867 Übrig/);
  assert.match(shown, /Frühstück 233 kcal/);
});

test("the preview scales the chosen food", () => {
  const food = { kcal: 389, protein: 16.9, carbs: 66, fat: 6.9 };
  assert.equal(text(fn.previewHTML(food, 60, "en-GB", en())), "233 kcal 10.1 Protein (g) 39.6 Carbs (g) 4.1 Fat (g)");
  assert.equal(text(fn.previewHTML(food, null, "en-GB", en())), "– kcal – Protein (g) – Carbs (g) – Fat (g)");
});

test("an entry logged by weight is edited by grams, a quick add by kcal", () => {
  const byWeight = fn.editPanelHTML({ entry: DAY.entries[0] }, "en-GB", en());
  assert.match(byWeight, /data-field="grams"[^>]*value="60"/);
  const quick = fn.editPanelHTML({ entry: DAY.entries[1] }, "en-GB", en());
  assert.match(quick, /data-field="kcal"[^>]*value="900"/);
  const confirming = text(fn.editPanelHTML({ entry: DAY.entries[1], confirming: true }, "en-GB", en()));
  assert.match(confirming, /Delete Pizza <large>\? Cancel Yes, delete/);
});

test("the add panel has a tab for each way to add food", () => {
  const panel = fn.addPanelHTML({ kind: "add", meal: "lunch", tab: "quick", query: "" }, en());
  assert.match(text(panel), /^Add to Lunch Cancel Saved foods Quick add New food Name kcal/);
  assert.match(panel, /aria-selected="true">Quick add/);
});

test("the food form shows a food's values and portions, escaped", () => {
  const form = fn.foodFormHTML({ name: 'Oats "fine"', kcal: 389, protein: 16.9, carbs: 66, fat: 6.9, portions: [{ name: "Bowl", grams: 40 }] }, en());
  assert.match(form, /data-field="name"[^>]*value="Oats &quot;fine&quot;"/);
  assert.match(form, /data-portion="grams"[^>]*value="40"/);
  assert.match(form, /data-field="salt"[^>]*value=""/);
});

test("the foods list says when nothing matches", () => {
  assert.equal(text(fn.foodsListHTML([], "", "en", en())), "No saved foods yet. Add the foods you eat often.");
  assert.equal(text(fn.foodsListHTML([], "kiwi", "en", en())), "No saved food matches “kiwi”.");
  const list = text(fn.foodsListHTML([{ id: 1, name: "Oats", barcode: "5000", kcal: 389 }], "", "en", en()));
  assert.equal(list, "Oats 5000 389 kcal per 100 g");
});

test("cards reject config that is not text", () => {
  const Card = ctx.customElements.defined["zp-food-diary-card"];
  assert.throws(() => new Card().setConfig({ person: 3 }), /person: must be text/);
  assert.throws(() => new Card().setConfig(null), /Invalid configuration/);
  new Card().setConfig({});
});

test("languages fall back to their base language, then English", () => {
  const { STRINGS } = fn;
  assert.equal(fn.translate("pt-BR").title_diary, STRINGS.pt.title_diary);
  assert.equal(fn.translate("pt-BR").title_foods, STRINGS["pt-BR"].title_foods);
  assert.equal(fn.translate("zh-CN").title_diary, STRINGS["zh-Hans"].title_diary);
  assert.equal(fn.translate("xx").title_diary, STRINGS.en.title_diary);
});

test("every language has every English key, with the same placeholders", () => {
  const { STRINGS } = fn;
  const holes = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
  assert.equal(Object.keys(STRINGS).length, 11);
  for (const [lang, table] of Object.entries(STRINGS)) {
    if (lang !== "pt-BR") assert.deepEqual(Object.keys(table).sort(), Object.keys(STRINGS.en).sort(), lang);
    for (const [key, value] of Object.entries(table)) {
      assert.ok(key in STRINGS.en, `${lang}.${key}`);
      assert.deepEqual(holes(value), holes(STRINGS.en[key]), `${lang}.${key}`);
    }
  }
});
