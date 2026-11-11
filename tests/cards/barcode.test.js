// Barcodes: the Open Food Facts mapping and lookup, and the scanners.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain } = require("./harness.js");

let fn;
test.before(async () => {
  const ctx = await load();
  fn = vm.runInContext("({ translate, offFood, lookUpBarcode, mergeFood, scanWithApp, scannerFor, BARCODE })", ctx);
});

const YOGURT = {
  product_name: "Greek yogurt 2% ",
  brands: "Fage, Total",
  serving_quantity: "170",
  nutriments: {
    "energy-kcal_100g": 73,
    proteins_100g: 10,
    carbohydrates_100g: "3.6",
    fat_100g: 2,
    sugars_100g: 3.6,
    "saturated-fat_100g": 1.3,
    salt_100g: 0.1,
  },
};

test("an Open Food Facts product becomes a food per 100 g", () => {
  const food = plain(fn.offFood("5201054017111", YOGURT, "Serving"));
  assert.deepEqual(food, {
    name: "Greek yogurt 2% – Fage",
    barcode: "5201054017111",
    kcal: 73,
    protein: 10,
    carbs: 3.6,
    fat: 2,
    fibre: null,
    sugar: 3.6,
    saturated_fat: 1.3,
    salt: 0.1,
    portions: [{ name: "Serving", grams: 170 }],
  });
});

test("energy only in kJ is turned into kcal", () => {
  const food = fn.offFood("12345678", { product_name: "Oats", nutriments: { energy_100g: 1628 } }, "Serving");
  assert.equal(food.kcal, 389);
  assert.equal(food.protein, null);
  assert.equal(plain(food.portions).length, 0);
});

const reply = (status, body) => async () => ({ status, ok: status < 400, json: async () => body });

test("a lookup returns the product, or null when Open Food Facts has none", async () => {
  const seen = [];
  const found = await fn.lookUpBarcode("5201054017111", "Serving", async (url) => {
    seen.push(url);
    return reply(200, { status: 1, product: YOGURT })();
  });
  assert.equal(found.kcal, 73);
  assert.match(seen[0], /^https:\/\/world\.openfoodfacts\.org\/api\/v2\/product\/5201054017111\.json\?fields=/);
  assert.equal(await fn.lookUpBarcode("1", "S", reply(404, {})), null);
  assert.equal(await fn.lookUpBarcode("1", "S", reply(200, { status: 0 })), null);
  await assert.rejects(fn.lookUpBarcode("1", "S", reply(503, {})), /HTTP 503/);
});

test("what Open Food Facts knows fills the form, keeping a typed name and portions", () => {
  const found = fn.offFood("5201054017111", YOGURT, "Serving");
  const merged = plain(fn.mergeFood({ name: "My yogurt", kcal: 1, portions: [{ name: "Pot", grams: 150 }] }, found));
  assert.equal(merged.name, "My yogurt");
  assert.equal(merged.kcal, 73);
  assert.deepEqual(merged.portions, [{ name: "Pot", grams: 150 }]);
  assert.equal(fn.mergeFood({ portions: [] }, found).name, "Greek yogurt 2% – Fage");
});

test("barcodes are 8 to 14 digits", () => {
  assert.ok(fn.BARCODE.test("12345678"));
  assert.ok(fn.BARCODE.test("12345678901234"));
  assert.ok(!fn.BARCODE.test("1234567"));
  assert.ok(!fn.BARCODE.test("12345abc"));
});

// The frontend's handler for messages from the app, which acknowledges each.
function fakeApp() {
  const sent = [];
  const acked = [];
  const external = {
    config: { hasBarCodeScanner: 1 },
    fireMessage: (message) => sent.push(message),
    receiveMessage(message) {
      acked.push(message.id);
    },
  };
  return { external, sent, acked };
}

test("the app's scanner returns the code, closes, and keeps acknowledging", async () => {
  const { external, sent, acked } = fakeApp();
  const original = external.receiveMessage;
  const scanning = fn.scanWithApp(external, fn.translate("en"));
  assert.equal(sent[0].type, "bar_code/scan");
  assert.equal(sent[0].payload.title, "Scan a barcode");
  external.receiveMessage({ id: 7, type: "command", command: "bar_code/scan_result", payload: { rawValue: "5000", format: "ean_13" } });
  assert.equal(await scanning, "5000");
  assert.deepEqual(acked, [7]);
  assert.equal(sent[1].type, "bar_code/close");
  assert.equal(external.receiveMessage, original);
});

test("cancelling the app's scanner returns null", async () => {
  const { external } = fakeApp();
  const scanning = fn.scanWithApp(external, fn.translate("en"));
  external.receiveMessage({ id: 1, type: "result", success: true });
  external.receiveMessage({ id: 2, type: "command", command: "bar_code/aborted", payload: { reason: "canceled" } });
  assert.equal(await scanning, null);
});

test("the scanner is the app's, else the browser's, else none", () => {
  const browser = { BarcodeDetector: class {}, navigator: { mediaDevices: { getUserMedia() {} } } };
  assert.equal(fn.scannerFor({ auth: { external: { config: { hasBarCodeScanner: 1 } } } }, browser), "app");
  assert.equal(fn.scannerFor({ auth: {} }, browser), "camera");
  assert.equal(fn.scannerFor({ auth: {} }, { navigator: {} }), null);
});
