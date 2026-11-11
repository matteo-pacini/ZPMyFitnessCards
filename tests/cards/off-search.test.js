// Searching Open Food Facts by name: names, rows, and each state of the search.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain, text } = require("./harness.js");

let fn;
test.before(async () => {
  const ctx = await load();
  fn = vm.runInContext("({ translate, offLanguage, firstBrand, offName, searchedFood, offRowHTML, offSearchHTML })", ctx);
});

const en = () => fn.translate("en");

// As Search-a-licious gives it: brands as a list, no serving size.
const YOGURT = {
  code: "8017596079480",
  brands: ["Land", " Eurospin"],
  quantity: " 150 g",
  product_name: "Yogurt greco bianco",
  product_name_de: "Griechischer Joghurt",
  nutriments: { "energy-kcal_100g": 70.4, proteins_100g: 9, carbohydrates_100g: 4, fat_100g: 2, salt_100g: 0.18 },
};

test("a card's language searches as its base language", () => {
  assert.equal(fn.offLanguage("en"), "en");
  assert.equal(fn.offLanguage("pt-BR"), "pt");
  assert.equal(fn.offLanguage("zh-Hans"), "zh");
});

test("the first brand comes from a list or from comma-separated text", () => {
  assert.equal(fn.firstBrand([" Land", "Eurospin"]), "Land");
  assert.equal(fn.firstBrand("Fage, Total"), "Fage");
  assert.equal(fn.firstBrand([]), null);
  assert.equal(fn.firstBrand(""), null);
  assert.equal(fn.firstBrand(undefined), null);
});

test("names are in the card's language, else English, else the product's own", () => {
  assert.equal(fn.offName(YOGURT, "de"), "Griechischer Joghurt");
  assert.equal(fn.offName({ ...YOGURT, product_name_en: "Greek yogurt " }, "it"), "Greek yogurt");
  assert.equal(fn.offName({ ...YOGURT, product_name_de: " " }, "de"), "Yogurt greco bianco");
  assert.equal(fn.offName({ code: "1" }, "en"), "");
});

test("a searched product becomes a food per 100 g, named in the language, without portions", () => {
  assert.deepEqual(plain(fn.searchedFood(YOGURT, "de", "Serving")), {
    name: "Griechischer Joghurt – Land",
    barcode: "8017596079480",
    kcal: 70.4,
    protein: 9,
    carbs: 4,
    fat: 2,
    fibre: null,
    sugar: null,
    saturated_fat: null,
    salt: 0.18,
    portions: [],
  });
});

test("a result row shows the name, brand, pack size and kcal per 100 g, escaped", () => {
  const row = fn.offRowHTML({ ...YOGURT, product_name: "Yogurt <greco>" }, "en-GB", en());
  assert.match(row, /data-action="off-pick" data-code="8017596079480"/);
  assert.equal(text(row), "Yogurt <greco> Land · 150 g 70 kcal per 100 g");
  assert.match(row, /Yogurt &lt;greco&gt;/);
  const bare = fn.offRowHTML({ code: "12345678", nutriments: { "energy-kcal_100g": 1234 } }, "en-GB", en());
  assert.equal(text(bare), "12345678 1,234 kcal per 100 g");
});

const search = (more) => ({ query: "yogurt", products: [], page: 0, more: false, ...more });

test("an empty query gets a hint, and a barcode its own lookup", () => {
  assert.equal(text(fn.offSearchHTML("  ", undefined, "en", en())), "Type a name to search Open Food Facts too.");
  assert.equal(fn.offSearchHTML("5201054017111", undefined, "en", en()), "");
});

test("a typed name offers a search, and so does a name typed after one", () => {
  const button = fn.offSearchHTML(" greek yogurt ", undefined, "en", en());
  assert.match(button, /data-action="off-search"/);
  assert.equal(text(button), "Search Open Food Facts for “greek yogurt”");
  const after = fn.offSearchHTML("yogurt 0%", search({ products: [YOGURT], page: 1 }), "en", en());
  assert.equal(text(after), "Search Open Food Facts for “yogurt 0%”");
});

test("a search shows that it is busy, then its products and More", () => {
  assert.equal(text(fn.offSearchHTML("yogurt", search({ busy: true }), "en", en())), "From Open Food Facts Searching Open Food Facts…");
  const found = fn.offSearchHTML("yogurt", search({ products: [YOGURT], page: 1, more: true }), "en", en());
  assert.equal(text(found), "From Open Food Facts Yogurt greco bianco Land · 150 g 70 kcal per 100 g More");
  assert.match(found, /data-action="off-next">More/);
  const last = fn.offSearchHTML("yogurt", search({ products: [YOGURT], page: 2 }), "en", en());
  assert.doesNotMatch(last, /off-next/);
});

test("a search says when Open Food Facts has nothing", () => {
  const none = text(fn.offSearchHTML("yogurt", search({ page: 1 }), "en", en()));
  assert.equal(none, "From Open Food Facts Open Food Facts has no product matching “yogurt” with kcal, protein, carbs and fat.");
});

test("a failed search, or a failed More, says why and offers to try again", () => {
  const failed = fn.offSearchHTML("yogurt", search({ error: "HTTP 503" }), "en", en());
  assert.equal(text(failed), "From Open Food Facts Could not search Open Food Facts: HTTP 503 Try again");
  assert.match(failed, /data-action="off-next">Try again/);
  const more = fn.offSearchHTML("yogurt", search({ products: [YOGURT], page: 1, more: true, error: "" }), "en", en());
  assert.equal(text(more), "From Open Food Facts Yogurt greco bianco Land · 150 g 70 kcal per 100 g Could not search Open Food Facts: Try again");
});
