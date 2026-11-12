const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { sources } = require("../../scripts/build.js");
const { load, plain, text } = require("./harness.js");

let ctx;
let fn;
test.before(async () => {
  ctx = await load();
  fn = vm.runInContext(
    "({ STRINGS, translate, todayIn, shiftDay, dayLabel, scaled, totals, findPerson, diaryBodyHTML, previewHTML, foodsListHTML, foodFormHTML, editPanelHTML, addPanelHTML, panelMessagesHTML, cancelButtonHTML, amountField, chooseFood, showSavedFood, diarySummaryHTML, mealHTML, resultsHTML, pickedHTML })",
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

test("the diary's summary takes the day's totals from its goal", () => {
  const sums = { kcal: 1500, protein: 50, carbs: 300, fat: 40 };
  const goals = { kcal: 2000, protein: 100, carbs: 250, fat: 0 };
  const shown = text(fn.diarySummaryHTML(sums, goals, en(), "en-GB"));
  assert.equal(shown, "2,000 Goal − 1,500 Food = 500 Remaining Protein 50 / 100 g Carbs 300 / 250 g Fat 40 / 0 g");
  // A goal of 0 g fills no bar and is never over.
  assert.match(fn.diarySummaryHTML(sums, goals, en(), "en-GB"), /class="macro fat"><small>Fat<\/small>\s*<div class="bar"><i style="width:0%">/);
  assert.equal(text(fn.diarySummaryHTML(sums, null, en(), "en-GB")), "1,500 Food");
});

test("a meal lists its entries, or says nothing is logged", () => {
  const dinner = text(fn.mealHTML("dinner", [DAY.entries[1]], en(), "en-GB"));
  assert.equal(dinner, "Dinner 900 kcal Pizza <large> 900 + Add food Copy Save as meal");
  assert.match(fn.mealHTML("dinner", [DAY.entries[1]], en(), "en-GB"), /data-action="save-as-meal" data-meal="dinner"/);
  // Only a meal with something in it can be saved.
  assert.equal(text(fn.mealHTML("lunch", [], en(), "en-GB")), "Lunch Nothing logged yet + Add food Copy");
  assert.match(fn.mealHTML("lunch", [], en(), "en-GB"), /data-action="copy" data-meal="lunch"/);
});

test("search results say why they are empty, and list only saved foods", () => {
  assert.equal(text(fn.resultsHTML({ query: "", results: undefined }, "en-GB", en())), "Loading…");
  assert.equal(text(fn.resultsHTML({ query: "kiwi", results: [] }, "en-GB", en())), "No saved food matches “kiwi”.");
  assert.doesNotMatch(fn.resultsHTML({ query: "5000112637922", results: [] }, "en-GB", en()), /<button/);
});

test("search results list foods by kcal per 100 g, the chosen one pressed", () => {
  const oats = { id: 1, name: "Oats", kcal: 389 };
  const html = fn.resultsHTML({ query: "oa", results: [oats, { id: 2, name: "Oat milk", kcal: 46 }], food: oats }, "en-GB", en());
  assert.match(text(html), /^Saved foods Oats 389 kcal per 100 g Oat milk 46 kcal per 100 g$/);
  assert.match(html, /data-id="1" aria-pressed="true"/);
  assert.match(html, /data-id="2" aria-pressed="false"/);
});

test("a picked food offers its portions and the meal to add it to", () => {
  assert.equal(fn.pickedHTML({ query: "" }, "en-GB", en()), "");
  const food = { id: 1, name: "Oats", kcal: 389, portions: [{ name: "Bowl", grams: 40 }] };
  const html = fn.pickedHTML({ food, grams: 40, meal: "lunch" }, "en-GB", en());
  assert.match(html, /data-field="grams"[^>]*value="40"/);
  assert.match(html, /<option value="lunch" selected>/);
  assert.match(text(html), /Bowl · 40 g Add to Lunch$/);
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
  assert.equal(fn.amountField(DAY.entries[0]), "grams");
  assert.equal(fn.amountField(DAY.entries[1]), "kcal");
  const confirming = text(fn.editPanelHTML({ entry: DAY.entries[1], confirming: true }, "en-GB", en()));
  assert.match(confirming, /Delete Pizza <large>\? Cancel Yes, delete/);
});

test("a chosen food starts at its first portion, else 100 g", () => {
  const p = {};
  fn.chooseFood(p, { id: 1, portions: [{ name: "Bowl", grams: 40 }, { name: "Cup", grams: 80 }] });
  assert.equal(p.grams, 40);
  fn.chooseFood(p, { id: 2, portions: [] });
  assert.deepEqual(plain(p), { food: { id: 2, portions: [] }, grams: 100 });
  fn.chooseFood(p, { id: 3 });
  assert.equal(p.grams, 100);
});

test("a saved food shows chosen on the search tab, and clears the panel's note, warning and error", () => {
  const food = { id: 7, name: "Oats", portions: [{ name: "Bowl", grams: 40 }] };
  const p = { kind: "add", meal: "lunch", tab: "new", query: "", warning: "W", error: "E", note: "N" };
  fn.showSavedFood(p, food);
  assert.deepEqual(plain(p), {
    kind: "add", meal: "lunch", tab: "search", query: "Oats", results: [food], food, grams: 40, chosen: null, newFood: null, review: false,
    note: null, warning: null, error: null, retry: null, taken: null,
  });
});

test("a panel shows its note, warning and error, in that order, escaped", () => {
  assert.equal(fn.panelMessagesHTML({}), "");
  assert.equal(
    fn.panelMessagesHTML({ note: "N", warning: null, error: "<E>" }),
    '<div class="note">N</div><div class="error">&lt;E&gt;</div>',
  );
  assert.equal(text(fn.panelMessagesHTML({ error: "E", warning: "W", note: "N" })), "N W E");
});

test("a panel's Cancel button closes it, in the card's language", () => {
  assert.equal(fn.cancelButtonHTML(fn.translate("de")), '<button class="text" data-action="close">Abbrechen</button>');
});

test("the add panel has a tab for each way to add food", () => {
  const panel = fn.addPanelHTML({ kind: "add", meal: "lunch", tab: "quick", query: "" }, en());
  assert.match(text(panel), /^Add to Lunch Cancel Saved Quick add New food Name kcal/);
  assert.match(panel, /aria-selected="true">Quick add/);
});

test("the add panel has one Scan, in its head, where the device can scan", () => {
  for (const tab of ["search", "quick", "new"]) {
    const panel = fn.addPanelHTML({ kind: "add", meal: "lunch", tab, query: "" }, en(), true);
    assert.match(panel, /<span class="headactions"><button class="text" data-action="scan">Scan<\/button><button class="text" data-action="close">/, tab);
    assert.equal(panel.match(/data-action="(off-)?scan"/g).length, 1, tab);
    assert.equal(panel.match(/class="scanner"/g).length, 1, tab);
    assert.doesNotMatch(fn.addPanelHTML({ kind: "add", meal: "lunch", tab, query: "" }, en(), false), /data-action="scan"/, tab);
  }
});

test("what was typed in Quick add shows again", () => {
  const quick = { name: "Pizza <slice>", kcal: "300", protein: "", carbs: "40", fat: "12", meal: "dinner" };
  const panel = fn.addPanelHTML({ kind: "add", meal: "lunch", tab: "quick", query: "", quick }, en());
  assert.match(panel, /data-field="name" value="Pizza &lt;slice&gt;"/);
  assert.match(panel, /data-field="kcal" [^>]*value="300"/);
  assert.match(panel, /data-field="carbs" [^>]*value="40"/);
  assert.match(panel, /<option value="dinner" selected>/);
});

test("a lookup that is running shows, with Cancel", () => {
  const panel = fn.addPanelHTML({ kind: "add", meal: "lunch", tab: "new", query: "", lookup: { code: "5201054025321" } }, en());
  assert.match(text(panel), /Looking up 5201054025321… Cancel Saved/);
  assert.match(panel, /data-action="cancel-lookup"/);
});

test("New food shows a product from Open Food Facts as a short check", () => {
  const food = { name: "Skyr – Arla", barcode: "5701211074552", kcal: 63, protein: 11, carbs: 4, fat: 0.2, portions: [{ name: "Serving", grams: 150 }] };
  const panel = fn.addPanelHTML({ kind: "add", meal: "lunch", tab: "new", query: "", newFood: food, review: true }, en(), false, "en-GB");
  assert.doesNotMatch(panel, /class="foodform"/);
  assert.match(text(panel), /Skyr – Arla 5701211074552 Edit values Per 100 g 63 kcal 11 Protein \(g\) 4 Carbs \(g\) 0.2 Fat \(g\) Serving · 150 g Cancel Save and choose/);
  assert.match(fn.addPanelHTML({ kind: "add", meal: "lunch", tab: "new", query: "", newFood: food }, en()), /class="foodform"/);
});

test("New food starts with a search of Open Food Facts, and its form has no barcode buttons", () => {
  const panel = fn.addPanelHTML({ kind: "add", meal: "lunch", tab: "new", query: "", offQuery: "skyr" }, en(), true);
  assert.ok(panel.indexOf('data-action="off-query"') < panel.indexOf('class="foodform"'));
  assert.match(panel, /data-action="off-query" value="skyr"/);
  // Scan is in the panel's head instead.
  assert.doesNotMatch(panel, /data-action="(lookup|off-scan)"/);
});

test("the food form shows a food's values and portions, escaped", () => {
  const form = fn.foodFormHTML({ name: 'Oats "fine"', kcal: 389, protein: 16.9, carbs: 66, fat: 6.9, portions: [{ name: "Bowl", grams: 40 }] }, en());
  assert.match(form, /data-field="name"[^>]*value="Oats &quot;fine&quot;"/);
  assert.match(form, /data-portion="grams"[^>]*value="40"/);
  assert.match(form, /data-field="salt"[^>]*value=""/);
  assert.match(form, /data-action="lookup"/);
  assert.match(fn.foodFormHTML({}, en(), true), /data-action="scan"/);
  assert.doesNotMatch(fn.foodFormHTML({}, en(), true, false), /data-action="(lookup|scan)"|class="scanner"/);
});

test("the foods list says when nothing matches", () => {
  assert.equal(text(fn.foodsListHTML([], "", "en", en())), "No saved foods yet. Add the foods you eat often.");
  assert.equal(text(fn.foodsListHTML([], "kiwi", "en", en())), "No saved food matches “kiwi”.");
  const list = text(fn.foodsListHTML([{ id: 1, name: "Oats", barcode: "5000", kcal: 389 }], "", "en", en()));
  assert.equal(list, "Oats 5000 389 kcal per 100 g");
});

test("cards reject config that is not text", () => {
  const Card = ctx.customElements.defined["metron-food-diary-card"];
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

test("each language file is in the bundle, and holds that language alone", () => {
  const dir = path.join(__dirname, "..", "..", "src", "cards", "strings");
  const files = fs.readdirSync(dir).map((name) => path.join(dir, name));
  assert.deepEqual(files.filter((file) => !sources.includes(file)), [], "add them to SOURCES in scripts/build.js");
  for (const file of files) {
    const strings = vm.runInNewContext(`const STRINGS = {};\n${fs.readFileSync(file, "utf8")}\nSTRINGS`);
    assert.deepEqual(Object.keys(strings), [path.basename(file, ".js")], file);
  }
});
