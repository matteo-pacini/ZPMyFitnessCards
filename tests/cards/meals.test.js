// Saved meals and who saved what: the markup the food diary, saved foods and
// saved meals cards build for them, and the pure functions behind it.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain, text } = require("./harness.js");

let ctx;
let fn;
test.before(async () => {
  ctx = await load();
  fn = vm.runInContext(
    `({ translate, personName, ownerPillHTML, savedByPillHTML, listText, nameMatches, mealRowHTML, amountTagHTML, tickListHTML,
        totalsHTML, ticked, mealExistsText, takenText, reviewHTML, reviewable, lookingUpHTML, panelMessagesHTML, withMessages,
        resultsHTML, chosenMealHTML, saveMealPanelHTML, mealHTML, deleteAlertHTML, foodsListHTML, editableItem, foodItem, setGrams,
        itemToSave, mealsListHTML, itemEditorHTML, mealEditorHTML, addFoodResultsHTML, editorStrings, editorForm, DEFAULT_CHOICE })`,
    ctx,
  );
});

const en = () => fn.translate("en");
const de = () => fn.translate("de");
const PEOPLE = [
  { id: "debora", name: "Debora" },
  { id: "matteo", name: "Matteo" },
];
const OATS = { id: 11, name: "Porridge oats", kcal: 389, protein: 13.2, carbs: 60, fat: 7, portions: [{ name: "Bowl", grams: 60 }], saved_by: "debora" };
const item = (id, name, grams, kcal, extra = {}) => ({ id, food_id: 100 + id, name, grams, kcal, protein: 1, carbs: 2, fat: 3, ...extra });
const coffee = { id: 9, food_id: null, name: "Coffee", grams: null, kcal: 20, protein: 1, carbs: 1.5, fat: 1 };
const meal = (id, name, owner, items) => ({ id, name, owner, version: 1, items });
const PORRIDGE = meal(1, "Porridge bowl", null, [item(1, "Porridge oats", 60, 227.4), item(2, "Semi-skimmed milk", 200, 98), item(3, "Honey", 21, 63.8)]);
const SHAKE = meal(2, "Post-workout shake", "matteo", [item(4, "Whey", 30, 120), coffee]);
const PASTA = meal(3, "Pasta night", null, [item(5, "Spaghetti", 80, 287)]);
const OATS_MEAL = meal(4, "Overnight oats", null, [item(6, "Oats", 50, 190)]);
const MEALS = [OATS_MEAL, PASTA, PORRIDGE, SHAKE];

// Pills, names and lists

test("a meal's owner shows as Everyone or the person's name", () => {
  assert.equal(fn.ownerPillHTML(null, PEOPLE, en()), '<span class="pill everyone">Everyone</span>');
  assert.equal(fn.ownerPillHTML("matteo", PEOPLE, en()), '<span class="pill">Matteo</span>');
  assert.equal(fn.ownerPillHTML("nobody", PEOPLE, en()), "");
  assert.equal(text(fn.ownerPillHTML(null, PEOPLE, de())), "Alle");
  assert.equal(fn.personName(PEOPLE, "debora"), "Debora");
  assert.equal(fn.personName(undefined, "debora"), null);
});

test("a food shows who saved it, when that is known", () => {
  assert.equal(fn.savedByPillHTML(OATS, PEOPLE), '<span class="pill">Debora</span>');
  assert.equal(fn.savedByPillHTML({ ...OATS, saved_by: null }, PEOPLE), "");
  assert.equal(fn.savedByPillHTML({ ...OATS, saved_by: "gone" }, PEOPLE), "");
  assert.equal(fn.savedByPillHTML({ ...OATS, saved_by: "<b>" }, [{ id: "<b>", name: "<i>" }]), '<span class="pill">&lt;i&gt;</span>');
});

test("names join as the language joins a list", () => {
  assert.equal(fn.listText(["A"], "en"), "A");
  assert.equal(fn.listText(["A", "B", "C"], "en"), "A, B, and C");
  assert.equal(fn.listText(["A", "B", "C"], "en-GB"), "A, B and C");
  assert.equal(fn.listText(["A", "B"], "de"), "A und B");
});

test("names match a query anywhere, ignoring case and spaces around it", () => {
  assert.ok(fn.nameMatches("Porridge bowl", " BOWL "));
  assert.ok(fn.nameMatches("Äpfel", "äpf"));
  assert.ok(fn.nameMatches("Anything", ""));
  assert.ok(!fn.nameMatches("Porridge", "pasta"));
});

// Meals as rows, items to tick and totals

test("a meal's row has its name, owner, foods and kcal", () => {
  const row = fn.mealRowHTML(SHAKE, PEOPLE, "en-GB", en(), "choose-meal");
  assert.equal(text(row), "Post-workout shake Matteo Whey, Coffee 140 kcal");
  assert.match(row, /^<button class="row mealrow" data-action="choose-meal" data-id="2">/);
  assert.doesNotMatch(row, /aria-pressed/);
  assert.match(fn.mealRowHTML(SHAKE, PEOPLE, "en-GB", en(), "edit-meal", true), /data-action="edit-meal" data-id="2" aria-pressed="true"/);
  const odd = meal(5, "<Fish & chips>", null, [item(1, 'A "b"', 1, 1)]);
  assert.match(fn.mealRowHTML(odd, PEOPLE, "en", en(), "x"), /&lt;Fish &amp; chips&gt;.*A &quot;b&quot;/s);
});

test("an item's amount says grams, and Quick add when it has no saved food", () => {
  assert.equal(text(fn.amountTagHTML(item(1, "Oats", 60.5, 1), "en-GB", en())), "60.5 g");
  assert.equal(text(fn.amountTagHTML(coffee, "en-GB", en())), "Quick add");
  assert.equal(text(fn.amountTagHTML({ ...coffee, grams: 250 }, "en-GB", en())), "250 g · Quick add");
  assert.equal(fn.amountTagHTML({ food_id: 3, grams: null }, "en", en()), "");
  assert.equal(text(fn.amountTagHTML({ ...coffee, grams: 1250 }, "de", de())), "1.250 g · Schnell eintragen");
});

test("a tick list ticks what is ticked, each with its amount and kcal", () => {
  const html = fn.tickListHTML(SHAKE.items, [true, false], "en-GB", en());
  assert.equal(text(html), "Whey 30 g 120 Coffee Quick add 20");
  assert.match(html, /data-action="tick" data-index="0" checked>/);
  assert.match(html, /data-action="tick" data-index="1">/);
  assert.match(fn.tickListHTML([{ name: "x", kcal: null, food_id: 1, grams: 1 }], [true], "en", en()), /<span class="num">0<\/span>/);
});

test("totals add up kcal, protein, carbs and fat", () => {
  assert.equal(text(fn.totalsHTML(SHAKE.items, "en-GB", en())), "140 kcal 2 Protein (g) 3.5 Carbs (g) 4 Fat (g)");
  assert.equal(text(fn.totalsHTML([], "en-GB", en())), "0 kcal 0 Protein (g) 0 Carbs (g) 0 Fat (g)");
  assert.deepEqual(plain(fn.ticked(["a", "b", "c"], [true, false, true])), ["a", "c"]);
});

// Messages

test("a clashing name says whose meal has it", () => {
  const err = (owner) => ({ code: "meal_exists", translation_placeholders: { owner } });
  assert.equal(fn.mealExistsText(err(""), "Pasta night", PEOPLE, en()), "There is already a meal called “Pasta night” for everyone.");
  assert.equal(fn.mealExistsText(err("debora"), "Usual breakfast", PEOPLE, en()), "Debora already has a meal called “Usual breakfast”.");
  assert.equal(fn.mealExistsText(err("ghost"), "X", PEOPLE, en()), "ghost already has a meal called “X”.");
  assert.equal(fn.mealExistsText({}, "X", PEOPLE, en()), "There is already a meal called “X” for everyone.");
});

test("a food saved already says who saved it, when that is known", () => {
  const taken = (saved_by) => ({ food_id: "7", name: "Oat drink", saved_by });
  assert.equal(fn.takenText("barcode_taken", taken("debora"), PEOPLE, en()), "Debora already saved this as Oat drink.");
  assert.equal(fn.takenText("barcode_taken", taken(""), PEOPLE, en()), "Already saved as Oat drink.");
  assert.equal(fn.takenText("name_taken", taken("matteo"), PEOPLE, en()), "Oat drink is already saved by Matteo.");
  assert.equal(fn.takenText("name_taken", taken(""), PEOPLE, en()), "Oat drink is already saved.");
});

test("panel messages offer Try again and the choice a name warning asks for", () => {
  assert.equal(fn.panelMessagesHTML({ error: "E", retry: "5000" }), '<div class="error">E</div>');
  const retry = fn.panelMessagesHTML({ error: "E", retry: "5000" }, en());
  assert.equal(text(retry), "E Try again");
  assert.match(retry, /<div class="inline"><button class="text" data-action="retry-lookup">Try again<\/button><\/div>$/);
  const taken = fn.panelMessagesHTML({ warning: "W", taken: { food_id: "1" } }, en());
  assert.equal(text(taken), "W Choose it Save anyway");
  assert.match(taken, /data-action="choose-taken".*data-action="save-anyway"/);
  assert.equal(fn.panelMessagesHTML({}, en()), "");
});

test("messages go above a panel's last row of buttons, or at its end", () => {
  const html = '<div class="actions"><button>A</button></div><input><div class="actions"><button>B</button></div>';
  assert.equal(
    fn.withMessages(html, { error: "E" }, en()),
    '<div class="actions"><button>A</button></div><input><div class="error">E</div><div class="actions"><button>B</button></div>',
  );
  assert.equal(fn.withMessages("<input>", { note: "N" }, en()), '<input><div class="note">N</div>');
  assert.equal(fn.withMessages("<input>", {}, en()), "<input>");
});

// Barcodes and Open Food Facts

test("a product from Open Food Facts shows as a short check", () => {
  const food = { name: "Skyr <natural>", barcode: "5701211074552", kcal: 63, protein: 11, carbs: 4, fat: 0.2, portions: [{ name: "Serving", grams: 150 }] };
  const html = fn.reviewHTML(food, "en-GB", en());
  assert.equal(text(html), "Skyr <natural> 5701211074552 Edit values Per 100 g 63 kcal 11 Protein (g) 4 Carbs (g) 0.2 Fat (g) Serving · 150 g");
  assert.match(html, /data-action="edit-values"/);
  assert.match(html, /Skyr &lt;natural&gt;/);
  const plainFood = fn.reviewHTML({ ...food, barcode: null, portions: [] }, "en-GB", en());
  assert.doesNotMatch(plainFood, /class="chips"|<small class="num">/);
});

test("only a product with a name, kcal, protein, carbs and fat gets a short check", () => {
  const food = { name: "Skyr", kcal: 63, protein: 11, carbs: 4, fat: 0 };
  assert.ok(fn.reviewable(food));
  assert.ok(!fn.reviewable({ ...food, name: "" }));
  assert.ok(!fn.reviewable({ ...food, fat: null }));
  assert.ok(!fn.reviewable({ ...food, kcal: -1 }));
});

test("a running lookup says what it looks up, with Cancel", () => {
  const html = fn.lookingUpHTML("<5000>", en());
  assert.equal(text(html), "Looking up <5000>… Cancel");
  assert.match(html, /&lt;5000&gt;/);
  assert.match(html, /class="spinner"/);
  assert.match(html, /data-action="cancel-lookup"/);
  assert.equal(text(fn.lookingUpHTML("1", de())), "1 wird gesucht… Abbrechen");
});

// The food diary

const addPanel = (extra) => ({ kind: "add", meal: "breakfast", tab: "search", query: "", ...extra });
const FOODS = [{ id: 2, name: "Greek yogurt 2%", kcal: 73 }, { id: 13, name: "Banana", kcal: 89 }];

test("before typing, the Saved tab lists the first three meals A to Z, then recent foods", () => {
  const html = fn.resultsHTML(addPanel({ meals: MEALS, results: FOODS }), "en-GB", en(), PEOPLE);
  assert.equal(
    text(html),
    "Saved meals Overnight oats Everyone Oats 190 kcal Pasta night Everyone Spaghetti 287 kcal Porridge bowl Everyone " +
      "Porridge oats, Semi-skimmed milk, Honey 389 kcal All meals (4) Recent Greek yogurt 2% 73 kcal per 100 g Banana 89 kcal per 100 g",
  );
  assert.match(html, /data-action="all-meals"/);
  const all = text(fn.resultsHTML(addPanel({ meals: MEALS, results: FOODS, allMeals: true }), "en-GB", en(), PEOPLE));
  assert.match(all, /Post-workout shake Matteo/);
  assert.doesNotMatch(all, /All meals/);
  // Three meals or fewer need no button.
  assert.doesNotMatch(fn.resultsHTML(addPanel({ meals: MEALS.slice(0, 3), results: FOODS }), "en", en(), PEOPLE), /all-meals/);
});

test("with no meals or recent foods, the Saved tab says so", () => {
  assert.equal(text(fn.resultsHTML(addPanel({ meals: [], results: [] }), "en", en())), en().no_recent);
  assert.equal(text(fn.resultsHTML(addPanel({ meals: [] }), "en", en())), "Loading…");
  assert.equal(
    text(fn.resultsHTML(addPanel({ meals: [PASTA], results: [] }), "en", en(), PEOPLE)),
    `Saved meals Pasta night Everyone Spaghetti 287 kcal ${en().no_recent}`,
  );
});

test("typing finds meals above saved foods", () => {
  const html = text(fn.resultsHTML(addPanel({ query: "porridge", meals: MEALS, results: [OATS] }), "en-GB", en(), PEOPLE));
  assert.equal(html, "Saved meals Porridge bowl Everyone Porridge oats, Semi-skimmed milk, Honey 389 kcal Saved foods Porridge oats 389 kcal per 100 g");
  // A meal matching, and no food, is not "nothing matches".
  assert.equal(text(fn.resultsHTML(addPanel({ query: "pasta", meals: MEALS, results: [] }), "en", en(), PEOPLE)), "Saved meals Pasta night Everyone Spaghetti 287 kcal");
  assert.equal(text(fn.resultsHTML(addPanel({ query: "kiwi", meals: MEALS, results: [] }), "en", en(), PEOPLE)), "No saved food matches “kiwi”.");
});

test("once a meal is chosen, the results shrink to it", () => {
  const html = fn.resultsHTML(addPanel({ query: "", meals: MEALS, results: FOODS, chosen: PORRIDGE }), "en-GB", en(), PEOPLE);
  assert.equal(text(html), "Porridge bowl Everyone Porridge oats, Semi-skimmed milk, Honey 389 kcal");
  assert.match(html, /aria-pressed="true"/);
});

test("a chosen meal offers its items to tick, the meal to add them to, and their totals", () => {
  const p = addPanel({ chosen: SHAKE, ticks: [true, false] });
  const html = fn.chosenMealHTML(p, "en-GB", en(), PEOPLE);
  assert.equal(text(html), "Post-workout shake Matteo Whey 30 g 120 Coffee Quick add 20 Meal Breakfast Lunch Dinner Snacks 120 kcal 1 Protein (g) 2 Carbs (g) 3 Fat (g) Add to Breakfast");
  assert.match(html, /data-action="log-meal">Add to Breakfast/);
  assert.match(html, /<option value="breakfast" selected>/);
  assert.match(fn.chosenMealHTML({ ...p, ticks: [false, false] }, "en", en(), PEOPLE), /data-action="log-meal" disabled>/);
  assert.match(text(fn.chosenMealHTML({ ...p, meal: "snacks" }, "en", en(), PEOPLE)), /Add to Snacks$/);
});

test("Save as meal shows only on a meal with entries", () => {
  const entries = [{ id: 1, meal: "lunch", name: "Soup", grams: null, kcal: 100 }];
  assert.match(fn.mealHTML("lunch", entries, en(), "en"), /data-action="save-as-meal" data-meal="lunch">Save as meal/);
  assert.doesNotMatch(fn.mealHTML("lunch", [], en(), "en"), /save-as-meal/);
});

test("Save as meal asks a name, ticks every entry, and keeps the meal the person's", () => {
  const entries = [
    { id: 1, food_id: 11, name: "Porridge oats", grams: 60, kcal: 227.4, protein: 7.9, carbs: 36, fat: 4.2 },
    { id: 2, food_id: null, name: "Coffee with milk", grams: null, kcal: 20, protein: 1, carbs: 1.5, fat: 1 },
  ];
  const p = { kind: "save-meal", meal: "breakfast", entries, ticks: [true, true], name: "Usual <breakfast>", share: false };
  const html = fn.saveMealPanelHTML(p, "en-GB", en());
  assert.equal(
    text(html),
    "Save Breakfast as a meal Name Porridge oats 60 g 227 Coffee with milk Quick add 20 247 kcal 8.9 Protein (g) 37.5 Carbs (g) 5.2 Fat (g) Share with everyone Cancel Save meal",
  );
  assert.match(html, /data-action="meal-name" data-field="meal-name" value="Usual &lt;breakfast&gt;"/);
  assert.match(html, /data-action="share">/);
  assert.match(fn.saveMealPanelHTML({ ...p, share: true }, "en", en()), /data-action="share" checked>/);
  assert.match(fn.saveMealPanelHTML({ ...p, ticks: [false, false] }, "en", en()), /data-action="save-meal" disabled>/);
  assert.equal(text(fn.saveMealPanelHTML(p, "de", de())).split(" ").slice(0, 4).join(" "), "Frühstück als Mahlzeit speichern");
});

// The saved foods card

test("deleting a food used by meals names them, and those it empties", () => {
  assert.equal(fn.deleteAlertHTML([], "en", en()), "");
  assert.equal(fn.deleteAlertHTML(undefined, "en", en()), "");
  const meals = [
    { id: 1, name: "Banana snack", owner: null, emptied: true },
    { id: 2, name: "Post-workout shake", owner: "matteo", emptied: false },
    { id: 3, name: "Usual breakfast", owner: "debora", emptied: false },
  ];
  assert.equal(
    text(fn.deleteAlertHTML(meals, "en-GB", en())),
    "It is also in Banana snack, Post-workout shake and Usual breakfast, and will be removed from them. Banana snack will be deleted too, as nothing else is in it.",
  );
  assert.equal(text(fn.deleteAlertHTML(meals.slice(1), "en-GB", en())), "It is also in Post-workout shake and Usual breakfast, and will be removed from them.");
  assert.match(text(fn.deleteAlertHTML(meals, "de", de())), /^Es ist auch in Banana snack, Post-workout shake und Usual breakfast/);
});

test("saved foods show who saved them", () => {
  assert.equal(text(fn.foodsListHTML([OATS, { ...OATS, id: 12, name: "Kiwi", saved_by: null, barcode: "5000" }], "", "en", en(), PEOPLE)), "Porridge oats Debora 389 kcal per 100 g Kiwi 5000 389 kcal per 100 g");
});

// The saved meals card

test("meals list A to Z in the card's language, filtered by the search", () => {
  const list = fn.mealsListHTML(MEALS, "", PEOPLE, "en", en());
  assert.deepEqual([...list.matchAll(/class="mname">([^<]+)/g)].map((m) => m[1]), ["Overnight oats", "Pasta night", "Porridge bowl", "Post-workout shake"]);
  assert.match(list, /data-action="edit-meal"/);
  assert.equal(text(fn.mealsListHTML(MEALS, " PASTA ", PEOPLE, "en", en())), "Pasta night Everyone Spaghetti 287 kcal");
  assert.equal(text(fn.mealsListHTML(MEALS, "kiwi", PEOPLE, "en", en())), "No saved meal matches “kiwi”.");
  assert.equal(text(fn.mealsListHTML([], "", PEOPLE, "en", en())), en().meals_empty);
});

test("an item keeps its food's values per 100 g, and follows new grams", () => {
  const editable = fn.editableItem(item(1, "Oats", 50, 190, { fibre: null }));
  assert.equal(editable.per100g.kcal, 380);
  assert.equal(editable.per100g.fibre, null);
  fn.setGrams(editable, 75);
  assert.deepEqual([editable.grams, editable.kcal, editable.protein, editable.fibre], [75, 285, 1.5, null]);
  fn.setGrams(editable, null);
  assert.equal(editable.kcal, null);
  // Fixed values stay as they are.
  assert.deepEqual(plain(fn.editableItem(coffee)), coffee);
});

test("a saved food becomes an item at its first portion, else 100 g", () => {
  const added = fn.foodItem(OATS);
  assert.deepEqual([added.food_id, added.name, added.grams], [11, "Porridge oats", 60]);
  assert.ok(Math.abs(added.kcal - 233.4) < 1e-9);
  const plainFood = fn.foodItem({ ...OATS, portions: [] });
  assert.deepEqual([plainFood.grams, plainFood.kcal], [100, 389]);
});

test("items are saved as a food and grams, or fixed values; unfinished ones are refused", () => {
  assert.deepEqual(plain(fn.itemToSave({ food_id: 3, grams: 40, name: "x", kcal: 1 })), { food_id: 3, grams: 40 });
  assert.equal(fn.itemToSave({ food_id: 3, grams: 0 }), null);
  assert.equal(fn.itemToSave({ food_id: 3, grams: null }), null);
  assert.deepEqual(plain(fn.itemToSave({ ...coffee, name: " Coffee " })), {
    name: "Coffee",
    grams: null,
    kcal: 20,
    protein: 1,
    carbs: 1.5,
    fat: 1,
    fibre: null,
    sugar: null,
    saturated_fat: null,
    salt: null,
  });
  for (const broken of [{ name: " " }, { kcal: null }, { kcal: -1 }, { protein: -2 }]) assert.equal(fn.itemToSave({ ...coffee, ...broken }), null);
});

test("the editor takes grams for a saved food, and a name and values for fixed ones", () => {
  const linked = fn.itemEditorHTML(item(1, "Oats", 50, 190), 0, "en", en());
  assert.equal(text(linked), "Oats g 190 Remove");
  assert.match(linked, /data-action="item-grams" data-index="0" [^>]*value="50"/);
  assert.match(linked, /class="num kcal" data-index="0"/);
  const fixed = fn.itemEditorHTML({ ...coffee, name: '"Brew"' }, 2, "en", en());
  assert.equal(text(fixed), "Quick add Remove kcal Protein (g) Carbs (g) Fat (g)");
  assert.match(fixed, /data-key="name" data-index="2" value="&quot;Brew&quot;"/);
  for (const [key, value] of [["kcal", 20], ["protein", 1], ["carbs", 1.5], ["fat", 1]]) {
    assert.match(fixed, new RegExp(`data-key="${key}" data-index="2" [^>]*value="${value}"`));
  }
  assert.match(fixed, /data-action="remove-item" data-index="2"/);
});

test("the editor shows who a meal is for, its items, a search to add foods, and totals", () => {
  const p = { meal: SHAKE, name: SHAKE.name, owner: "matteo", items: SHAKE.items.map(fn.editableItem), addQuery: "", addResults: null };
  const html = fn.mealEditorHTML(p, PEOPLE, "en-GB", en());
  assert.equal(
    text(html),
    "Post-workout shake Name For Everyone Debora Matteo Foods Whey g 120 Remove Quick add Remove kcal Protein (g) Carbs (g) Fat (g) " +
      "Total 140 kcal 2 Protein (g) 3.5 Carbs (g) 4 Fat (g) Delete Cancel Save meal",
  );
  assert.match(html, /<option value="matteo" selected>Matteo/);
  assert.match(html, /placeholder="Add a saved food"/);
  // A new meal, for everyone, with nothing in it yet.
  const empty = fn.mealEditorHTML({ meal: null, name: "", owner: null, items: [], addQuery: "", addResults: null }, PEOPLE, "en", en());
  assert.match(text(empty), /^Add meal Name For Everyone Debora Matteo Foods – Total 0 kcal/);
  assert.match(empty, /<option value="" selected>Everyone/);
  assert.doesNotMatch(empty, /data-action="delete-meal"/);
  // Deleting asks first, saying logged entries stay.
  const confirming = text(fn.mealEditorHTML({ ...p, confirming: true }, PEOPLE, "en", en()));
  assert.match(confirming, /Entries already logged from it stay in the diary\. Delete Post-workout shake\? Cancel Yes, delete$/);
  assert.match(text(fn.mealEditorHTML({ ...p, error: "Taken" }, PEOPLE, "en", en())), /Taken Delete Cancel Save meal$/);
});

test("the editor's food search lists saved foods to add", () => {
  const p = (addResults, addQuery = "oat") => ({ addResults, addQuery });
  assert.equal(fn.addFoodResultsHTML(p(null), "en", en()), "");
  assert.equal(text(fn.addFoodResultsHTML(p([]), "en", en())), "No saved food matches “oat”.");
  const html = fn.addFoodResultsHTML(p([OATS]), "en", en());
  assert.equal(text(html), "Porridge oats 389 kcal per 100 g");
  assert.match(html, /data-action="add-item" data-id="11"/);
});

// The card editor

test("a card's editor can say another string, as the saved meals card does for its person", () => {
  const Card = ctx.customElements.defined["fork-and-scale-meals-card"];
  const t = fn.editorStrings(en(), Card.editorStrings);
  assert.equal(t.editor_person_linked, "All meals");
  assert.equal(t.editor_person_helper, "Shows everyone's meals and this person's own.");
  assert.equal(fn.editorStrings(en()).editor_person_linked, en().editor_person_linked);
  const { schema } = plain(fn.editorForm(Card.options, {}, PEOPLE, t));
  assert.deepEqual(schema[0].selector.select.options[0], { value: fn.DEFAULT_CHOICE, label: "All meals" });
  ctx.document = { createElement: (tag) => ({ tag }) };
  const editor = Card.getConfigElement();
  assert.deepEqual(plain(editor.strings), plain(Card.editorStrings));
});
