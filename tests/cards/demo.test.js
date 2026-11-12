// The design system's Home Assistant, design/demo-hass.js: it answers every
// command the cards send, with the integration's shapes, and design/build.js
// packs it with the cards into a script a page can inline.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { sources } = require("../../scripts/build.js");
const { load, plain } = require("./harness.js");

const DEMO = path.join(__dirname, "..", "..", "design", "demo-hass.js");
const TODAY = "2026-11-11";
const NOON = Date.parse(TODAY) + 43_200_000;

let demo;
test.before(() => {
  const ctx = vm.createContext({ Intl, setTimeout, clearTimeout, Response, console });
  vm.runInContext(fs.readFileSync(DEMO, "utf8"), ctx, { filename: DEMO });
  demo = vm.runInContext("({ DemoStore, demoHass, demoFetch, DEMO_BARCODE, DEMO_PRODUCTS, CARD_TYPES })", ctx);
});

// A hass on a fresh store, on TODAY.
const newHass = (options) => demo.demoHass(new demo.DemoStore(() => NOON), options);

// callWS's result, or its error as {error}.
const call = (hass, message) => hass.callWS(message).then(plain, (error) => ({ error: plain(error) }));

const people = async (hass) => Object.fromEntries((await call(hass, { type: "fork_and_scale/people" })).map((p) => [p.name, p.id]));

// Every command the cards send.
const COMMANDS = [...new Set(sources.flatMap((file) => [...fs.readFileSync(file, "utf8").matchAll(/type: "(fork_and_scale\/[a-z_/]+)"/g)].map((m) => m[1])))];

test("the demo answers every command the cards send", async () => {
  const hass = newHass();
  assert.ok(COMMANDS.length >= 18, COMMANDS);
  for (const type of COMMANDS) {
    const reply = await call(hass, { type });
    assert.notEqual(reply?.error?.code, "unknown_command", type);
  }
  assert.equal((await call(hass, { type: "fork_and_scale/nonsense" })).error.code, "unknown_command");
  const events = [];
  const stop = await hass.connection.subscribeMessage((e) => events.push(plain(e)), { type: "fork_and_scale/subscribe" });
  assert.equal(typeof stop, "function");
});

test("the demo mounts every card the cards register", () => {
  const registered = [...fs.readFileSync(path.join(__dirname, "..", "..", "src", "cards", "register.js"), "utf8").matchAll(/type: "([a-z-]+)"/g)].map((m) => m[1]);
  assert.deepEqual([...demo.CARD_TYPES].sort(), registered.sort());
});

test("people have what the cards read, and the user is linked to Debora", async () => {
  const hass = newHass();
  const all = await call(hass, { type: "fork_and_scale/people" });
  assert.deepEqual(all.map((p) => p.name), ["Matteo", "Debora"]);
  assert.deepEqual(Object.keys(all[1]).sort(), [
    "goal_weight_kg", "height_cm", "id", "name", "obese_from_kg", "overweight_from_kg", "person_entity", "start_date", "start_weight_kg", "underweight_below_kg",
  ]);
  assert.deepEqual([all[1].underweight_below_kg, all[1].overweight_from_kg, all[1].obese_from_kg], [50.4, 68.1, 81.7]);
  const linked = Object.values(hass.states).find((s) => s.attributes.user_id === hass.user.id);
  assert.equal(linked.entity_id, all[1].person_entity);
  assert.equal(hass.config.time_zone, "Europe/London");
  assert.equal(hass.config.unit_system.mass, "kg");
  assert.equal(newHass({ unitSystem: "us_customary" }).config.unit_system.mass, "lb");
  assert.equal(newHass({ locale: "it" }).locale.language, "it");
});

test("a day has its entries, goals and weight, as fork_and_scale/day gives them", async () => {
  const hass = newHass();
  const { Debora } = await people(hass);
  const day = await call(hass, { type: "fork_and_scale/day", person: Debora, day: TODAY });
  assert.equal(day.day, TODAY);
  assert.deepEqual(day.entries.map((e) => e.name), [
    "Porridge oats", "Greek yogurt 2%", "Banana", "Chicken breast, grilled", "Basmati rice, cooked", "Broccoli", "Olive oil", "Almonds",
  ]);
  assert.deepEqual(Object.keys(day.entries[0]), [
    "id", "person", "day", "meal", "food_id", "name", "grams", "kcal", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat", "salt", "created_at", "source",
  ]);
  assert.equal(day.entries[0].kcal, (389 * 60) / 100);
  // goals.py's maths for her, at 68.9 kg and 30 years old; carbs is a tie Python rounds to even.
  assert.deepEqual(day.goals, { kcal: 1634, protein: 81.7, carbs: 204.2, fat: 54.5 });
  assert.equal(day.weight_kg, 68.9);
  const empty = await call(hass, { type: "fork_and_scale/day", person: Debora, day: "2026-01-01" });
  assert.deepEqual(empty, { day: "2026-01-01", entries: [], goals: null, weight_kg: null });
});

test("days have totals by meal, goals and weight", async () => {
  const hass = newHass();
  const { Debora } = await people(hass);
  const { days } = await call(hass, { type: "fork_and_scale/days", person: Debora, start: "2026-11-04", end: TODAY });
  assert.equal(days.length, 8);
  assert.deepEqual(Object.keys(days[0]), ["day", "meals", "goals", "weight_kg"]);
  assert.deepEqual(Object.keys(days[0].meals), ["breakfast", "lunch", "dinner", "snacks"]);
  assert.deepEqual(Object.keys(days[0].meals.lunch), ["kcal", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat", "salt"]);
  assert.ok(days.every((d) => d.goals));
  assert.equal(days[7].weight_kg, 68.9);
  const backwards = await call(hass, { type: "fork_and_scale/days", person: Debora, start: TODAY, end: "2026-11-01" });
  assert.equal(backwards.error.code, "invalid_range");
});

test("Matteo has a year of weigh-ins", async () => {
  const hass = newHass();
  const { Matteo } = await people(hass);
  const weights = await call(hass, { type: "fork_and_scale/weights", person: Matteo });
  assert.equal(weights.length, 91);
  assert.deepEqual(weights[0], { day: "2025-11-16", kg: 94.5 });
  assert.equal(weights[90].day, TODAY);
});

test("writes answer as the integration does, and tell subscribers first", async () => {
  const hass = newHass();
  const { Debora } = await people(hass);
  const seen = [];
  await hass.connection.subscribeMessage((e) => seen.push(plain(e)), { type: "fork_and_scale/subscribe" });
  const added = hass.callWS({ type: "fork_and_scale/entry/add", person: Debora, day: TODAY, meal: "snacks", name: "Tea", kcal: 2 }).then((entry) => {
    seen.push("result");
    return plain(entry);
  });
  const entry = await added;
  assert.deepEqual(seen, [{ person: Debora, days: [TODAY] }, "result"]);
  assert.equal(entry.grams, null);
  assert.equal(entry.source, null);

  const moved = await call(hass, { type: "fork_and_scale/entry/update", entry_id: entry.id, day: "2026-11-10" });
  assert.equal(moved.day, "2026-11-10");
  assert.deepEqual(seen.at(-1), { person: Debora, days: ["2026-11-10", TODAY] });

  const food = await call(hass, { type: "fork_and_scale/food/add", name: " Skyr ", barcode: "1234567890123", kcal: 63, protein: 11, carbs: 4, fat: 0.2 });
  assert.equal(food.name, "Skyr");
  assert.deepEqual(food.portions, []);
  assert.equal(food.fibre, null);
  assert.deepEqual(seen.at(-1), { person: null, days: [] });
  const count = seen.length;
  const taken = await call(hass, { type: "fork_and_scale/food/add", name: "Other", barcode: "1234567890123", kcal: 1, protein: 1, carbs: 1, fat: 1 });
  assert.equal(taken.error.code, "barcode_taken");
  assert.equal(seen.length, count);

  const logged = await call(hass, { type: "fork_and_scale/entry/add", person: Debora, day: TODAY, meal: "lunch", food_id: food.id, grams: 150 });
  assert.equal(logged.kcal, (63 * 150) / 100);
  const doubled = await call(hass, { type: "fork_and_scale/entry/update", entry_id: logged.id, grams: 300 });
  assert.equal(doubled.kcal, 2 * logged.kcal);
  assert.equal((await call(hass, { type: "fork_and_scale/food/barcode", barcode: "1234567890123" })).id, food.id);
  assert.equal((await call(hass, { type: "fork_and_scale/food/recent", person: Debora }))[0].id, food.id);
  assert.equal(await call(hass, { type: "fork_and_scale/food/delete", food_id: food.id }), null);
  const day = await call(hass, { type: "fork_and_scale/day", person: Debora, day: TODAY });
  assert.equal(day.entries.find((e) => e.id === logged.id).food_id, null);

  assert.equal(await call(hass, { type: "fork_and_scale/weight/set", person: Debora, day: TODAY, kg: 67 }), null);
  assert.deepEqual(seen.at(-1), { person: Debora, days: [] });
  const lighter = await call(hass, { type: "fork_and_scale/day", person: Debora, day: TODAY });
  assert.equal(lighter.weight_kg, 67);
  assert.ok(lighter.goals.kcal < day.goals.kcal);

  const copied = await call(hass, { type: "fork_and_scale/meal/copy", person: Debora, from_day: "2026-11-10", from_meal: "dinner", to_day: TODAY, to_meal: "dinner" });
  assert.deepEqual(copied.map((e) => [e.name, e.day, e.meal]), [["Sample", TODAY, "dinner"]]);
});

test("refused messages get the integration's errors", async () => {
  const hass = newHass();
  const { Debora } = await people(hass);
  const error = async (message) => (await call(hass, message)).error;
  assert.deepEqual(await error({ type: "fork_and_scale/day", person: Debora, day: "2026-11-12" }), {
    code: "invalid_format",
    message: "in the future at 'day'. Got '2026-11-12'",
  });
  assert.deepEqual(await error({ type: "fork_and_scale/day", person: "nobody", day: TODAY }), { code: "not_found", message: "No such person" });
  assert.deepEqual(await error({ type: "fork_and_scale/entry/delete", entry_id: 99999 }), { code: "not_found", message: "Not found" });
  assert.deepEqual(await error({ type: "fork_and_scale/weight/set", person: Debora, day: TODAY, kg: 1000 }), {
    code: "invalid_format",
    message: "value must be at most 400 at 'kg'. Got 1000",
  });
  assert.deepEqual(await error({ type: "fork_and_scale/food/add", name: "", kcal: -1, extra: 1 }), {
    code: "invalid_format",
    message: "empty at 'name'. Got ''\nnot a valid option at 'extra'. Got 1\nnot a valid value at 'kcal'. Got -1",
  });
  assert.deepEqual(await error({ type: "fork_and_scale/food/add", name: "x", kcal: 1, portions: [{ name: "Cup", grams: 0 }] }), {
    code: "invalid_format",
    message: "not positive at 'portions[0].grams'. Got 0",
  });
  assert.equal((await error({ type: "fork_and_scale/food/add", name: "x", kcal: 1 })).message, "kcal, protein, carbs and fat are required");
  assert.equal((await error({ type: "fork_and_scale/entry/add", person: Debora, day: TODAY, meal: "lunch", food_id: 1 })).message, "grams is required with food_id");
  assert.equal((await error({ type: "fork_and_scale/openfoodfacts/search", query: "yogurt", language: "pt-BR" })).code, "invalid_format");
});

test("saved meals answer as the integration's do", async () => {
  const hass = newHass();
  const { Matteo: matteo, Debora: debora } = await people(hass);
  const all = await call(hass, { type: "fork_and_scale/meals" });
  assert.deepEqual(all.map((m) => [m.name, m.owner]), [["Chicken and rice", debora], ["Porridge with banana", null], ["Post-workout shake", matteo]]);
  assert.deepEqual((await call(hass, { type: "fork_and_scale/meals", person: debora })).map((m) => m.name), ["Chicken and rice", "Porridge with banana"]);
  const porridge = all[1];
  assert.deepEqual(porridge.items.map((i) => [i.name, i.grams, Math.round(i.kcal)]), [["Porridge oats", 60, 233], ["Banana", 120, 107]]);
  assert.equal(all[2].items[1].food_id, null);

  // Names clash within what one person sees.
  const coffee = [{ name: "Coffee", kcal: 20 }];
  const clash = await call(hass, { type: "fork_and_scale/meal/add", name: "PORRIDGE with banana", owner: debora, items: coffee });
  assert.equal(clash.error.code, "meal_exists");
  assert.deepEqual(clash.error.translation_placeholders, { owner: "" });
  const mine = await call(hass, { type: "fork_and_scale/meal/add", name: "Chicken and rice", owner: matteo, items: coffee });
  assert.equal(mine.owner, matteo);
  const theirs = await call(hass, { type: "fork_and_scale/meal/add", name: "chicken and rice", owner: null, items: coffee });
  assert.deepEqual(theirs.error.translation_placeholders, { owner: debora });

  // Logging takes the ticked items as they are, all or nothing.
  const entries = await call(hass, {
    type: "fork_and_scale/meal/log", person: debora, day: TODAY, meal: "snacks", meal_id: porridge.id, version: porridge.version, items: [porridge.items[1].id],
  });
  assert.deepEqual(entries.map((e) => [e.name, e.meal, e.grams]), [["Banana", "snacks", 120]]);
  const renamed = await call(hass, { type: "fork_and_scale/meal/update", meal_id: porridge.id, version: porridge.version, name: "Porridge" });
  assert.equal(renamed.version, porridge.version + 1);
  for (const message of [
    { type: "fork_and_scale/meal/log", person: debora, day: TODAY, meal: "lunch", meal_id: porridge.id, version: porridge.version, items: [porridge.items[0].id] },
    { type: "fork_and_scale/meal/delete", meal_id: porridge.id, version: porridge.version },
    { type: "fork_and_scale/meal/log", person: debora, day: TODAY, meal: "lunch", meal_id: mine.id, version: mine.version, items: [mine.items[0].id] },
  ]) {
    assert.equal((await call(hass, message)).error.code, "meal_changed");
  }

  // Deleting a food takes it out of its meals, and deletes those it empties.
  const banana = porridge.items[1].food_id;
  const using = await call(hass, { type: "fork_and_scale/food/meals", food_id: banana });
  assert.deepEqual(using.map((m) => [m.name, m.emptied]), [["Porridge", false], ["Post-workout shake", false]]);
  const single = await call(hass, { type: "fork_and_scale/meal/add", name: "Banana snack", owner: null, items: [{ food_id: banana, grams: 120 }] });
  assert.deepEqual((await call(hass, { type: "fork_and_scale/food/meals", food_id: banana })).map((m) => m.emptied), [true, false, false]);
  await call(hass, { type: "fork_and_scale/food/delete", food_id: banana });
  const left = await call(hass, { type: "fork_and_scale/meals" });
  assert.ok(!left.some((m) => m.id === single.id));
  assert.deepEqual(left.find((m) => m.name === "Porridge").items.map((i) => i.name), ["Porridge oats"]);
  assert.equal((await call(hass, { type: "fork_and_scale/meal/add", name: "x", owner: null, items: [{ food_id: banana, grams: 1 }] })).error.code, "not_found");
  assert.equal((await call(hass, { type: "fork_and_scale/meal/add", name: "x", owner: "nobody", items: coffee })).error.code, "not_found");
  assert.equal((await call(hass, { type: "fork_and_scale/meal/add", name: "x", owner: null, items: [] })).error.code, "invalid_format");
  assert.equal((await call(hass, { type: "fork_and_scale/meal/add", name: "x", owner: null, items: [{ name: "No kcal" }] })).error.code, "invalid_format");
});

test("saving a food records who saved it, and warns about one saved already", async () => {
  const hass = newHass();
  const { Debora: debora } = await people(hass);
  const oats = (await call(hass, { type: "fork_and_scale/food/search", query: "porridge oats" }))[0];
  assert.equal(oats.saved_by, debora);
  const food = { kcal: 1, protein: 1, carbs: 1, fat: 1 };
  const named = await call(hass, { type: "fork_and_scale/food/add", name: "PORRIDGE OATS", ...food });
  assert.equal(named.error.code, "name_taken");
  assert.deepEqual(named.error.translation_placeholders, { food_id: String(oats.id), name: "Porridge oats", saved_by: debora });
  const again = await call(hass, { type: "fork_and_scale/food/add", name: "Porridge oats", ...food, anyway: true });
  assert.equal(again.saved_by, null);
  const coded = await call(hass, { type: "fork_and_scale/food/add", name: "Coded", barcode: "5000", ...food, person: debora });
  const taken = await call(hass, { type: "fork_and_scale/food/add", name: "Other", barcode: "5000", ...food });
  assert.equal(taken.error.code, "barcode_taken");
  assert.deepEqual(taken.error.translation_placeholders, { food_id: String(coded.id), name: "Coded", saved_by: debora });
});

test("Open Food Facts searches give ten products a page", async () => {
  const hass = newHass();
  const first = await call(hass, { type: "fork_and_scale/openfoodfacts/search", query: " greek yogurt ", language: "it" });
  assert.equal(first.products.length, 10);
  assert.equal(first.more, true);
  assert.deepEqual(Object.keys(first.products[0]), ["code", "product_name", "brands", "quantity", "nutriments"]);
  assert.ok(first.products.every((p) => typeof p.nutriments["energy-kcal_100g"] === "number" && Array.isArray(p.brands)));
  assert.ok(first.products.some((p) => p.product_name_it === "Yogurt greco bianco" && p.product_name_en));
  const second = await call(hass, { type: "fork_and_scale/openfoodfacts/search", query: "greek yogurt", language: "it", page: 2 });
  assert.equal(second.more, false);
  assert.ok(second.products.length > 0);
  assert.deepEqual(await call(hass, { type: "fork_and_scale/openfoodfacts/search", query: "zzz", language: "en" }), { products: [], more: false });
});

test("barcode lookups answer from the sample products, and other requests go through", async () => {
  const passed = [];
  const fetch = demo.demoFetch(async (url) => {
    passed.push(url);
    return "real";
  });
  const found = await fetch(`https://world.openfoodfacts.org/api/v2/product/${demo.DEMO_BARCODE}.json?fields=product_name,brands,nutriments,serving_quantity`);
  assert.equal(found.status, 200);
  const body = await found.json();
  assert.equal(body.status, 1);
  assert.equal(body.product.brands, "Fage");
  assert.equal(body.product.serving_quantity, 170);
  assert.equal(body.product.nutriments["energy-kcal_100g"], 93);
  const unknown = await fetch("https://world.openfoodfacts.org/api/v2/product/00000000.json?fields=product_name");
  assert.equal(unknown.status, 404);
  assert.equal(await fetch("https://example.org/x.json"), "real");
  assert.deepEqual(passed, ["https://example.org/x.json"]);
});

test("the app's scanner answers a scan with the sample barcode, through receiveMessage", async () => {
  const external = newHass().auth.external;
  assert.equal(external.config.hasBarCodeScanner, true);
  const fired = [];
  const original = external.fireMessage;
  external.fireMessage = function (message) {
    fired.push(plain(message));
    original.call(this, message);
  };
  const received = await new Promise((resolve) => {
    const answer = external.receiveMessage;
    external.receiveMessage = function (message) {
      answer.call(this, message);
      resolve(plain(message));
    };
    external.fireMessage({ type: "bar_code/scan", payload: { title: "Scan", description: "Scan it" } });
  });
  assert.equal(received.command, "bar_code/scan_result");
  assert.equal(received.payload.rawValue, demo.DEMO_BARCODE);
  assert.deepEqual(fired.at(-1), { id: received.id, type: "result", success: true, result: null });
});

test("reset puts the sample data back and tells every subscriber", async () => {
  const store = new demo.DemoStore(() => NOON);
  const hass = demo.demoHass(store);
  await call(hass, { type: "fork_and_scale/food/add", name: "Extra", kcal: 1, protein: 1, carbs: 1, fat: 1 });
  const seen = [];
  await hass.connection.subscribeMessage((e) => seen.push(plain(e)), { type: "fork_and_scale/subscribe" });
  store.reset();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal((await call(hass, { type: "fork_and_scale/food/search", query: "" })).length, 10);
  assert.deepEqual(seen.map((e) => e.person).slice(-1), [null]);
  assert.equal(seen.length, 3);
});

test("design/build.js writes one classic script and the cards' shared styles", async () => {
  const { write, HEADER, SHARED_STYLES } = require("../../design/build.js");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fork-and-scale-design-"));
  try {
    await write(dir);
    const js = fs.readFileSync(path.join(dir, "components", "bundle.js"), "utf8");
    const css = fs.readFileSync(path.join(dir, "components", "bundle.css"), "utf8");
    assert.equal(js.split("\n")[0], '/* @ds-bundle: {"format":4,"namespace":"ForkAndScale","components":[]} */');
    assert.equal(js.split("\n")[0], HEADER);
    assert.doesNotMatch(js, /<\/script/i);
    assert.doesNotMatch(js, /<!--/);
    assert.doesNotMatch(js, /^\s*(import|export)\b/m);

    // It runs as a classic script, defines the cards, and leaves only its API behind.
    const defined = {};
    const ctx = vm.createContext({
      HTMLElement: class {},
      Intl,
      setTimeout,
      clearTimeout,
      customElements: { get: (name) => defined[name], define: (name, cls) => (defined[name] = cls), whenDefined: async () => {} },
    });
    ctx.window = ctx;
    vm.runInContext(js, ctx);
    await new Promise((r) => setImmediate(r));
    assert.ok(["home-assistant", "ha-card", "fork-and-scale-food-diary-card", "fork-and-scale-summary-card"].every((name) => defined[name]));
    assert.deepEqual(Object.keys(ctx.ForkAndScale).sort(), ["mount", "reset"]);
    assert.deepEqual(Object.keys(ctx).filter((k) => !["HTMLElement", "Intl", "setTimeout", "clearTimeout", "customElements", "window"].includes(k)).sort(), [
      "ForkAndScale",
      "customCards",
    ]);

    assert.ok(css.startsWith('@import url("https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap");\n'));
    assert.match(css, /^body \{ margin: 0; padding: 16px;/m);
    assert.match(css, /^ha-card \{ background: var\(--ha-card-background/m);
    const styles = vm.runInContext(SHARED_STYLES, await load());
    for (const [name, style] of Object.entries(styles)) {
      assert.ok(css.includes(`/* ${name} */`), name);
      for (const line of style.split("\n").filter((l) => l.trim())) assert.ok(css.includes(line.trim()), `${name}: ${line}`);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
