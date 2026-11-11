// Shared by the diary's "New food" tab and the saved foods card.
function foodFormHTML(food, t, scan = false) {
  const field = (key, label, value, extra = "") =>
    `<label>${esc(label)}<input data-field="${key}" ${extra} value="${value == null ? "" : esc(value)}"></label>`;
  const nutrient = (n) =>
    field(n, n === "kcal" ? t.kcal : `${t[n]} (g)`, food[n], `type="number" min="0" step="any" inputmode="decimal"`);
  const portions = (food.portions ?? []).map(
    (p, i) => `<div class="portion" data-index="${i}">
      <input data-portion="name" placeholder="${esc(t.portion_name)}" value="${esc(p.name ?? "")}" aria-label="${esc(t.portion_name)}">
      <input data-portion="grams" type="number" min="0" step="any" inputmode="decimal" placeholder="g" value="${p.grams ?? ""}" aria-label="${esc(t.grams)}">
      <button type="button" class="text" data-action="remove-portion" data-index="${i}">${esc(t.remove)}</button>
    </div>`,
  );
  return `<div class="foodform">
    <div class="grid">
      ${field("name", t.name, food.name)}
      ${field("barcode", `${t.barcode} (${t.optional})`, food.barcode, `inputmode="numeric"`)}
    </div>
    <div class="barcodes"><button type="button" class="text" data-action="lookup">${esc(t.look_up)}</button>${scan ? `<button type="button" class="text" data-action="scan">${esc(t.scan)}</button>` : ""}</div>
    <div class="scanner" hidden></div>
    <div class="sub">${esc(t.per_100g)}</div>
    <div class="grid">${REQUIRED_NUTRIENTS.map(nutrient).join("")}</div>
    <div class="sub">${esc(t.optional)}</div>
    <div class="grid">${OPTIONAL_NUTRIENTS.map(nutrient).join("")}</div>
    <div class="sub">${esc(t.portions)}</div>
    <div class="portions">${portions.join("")}</div>
    <div><button type="button" class="text" data-action="add-portion">+ ${esc(t.add_portion)}</button></div>
  </div>`;
}

// The food a filled-in food form describes, and an error key or null.
function readFoodForm(root) {
  const get = (key) => root.querySelector(`.foodform [data-field="${key}"]`);
  const food = { name: get("name").value.trim(), barcode: get("barcode").value.trim() || null };
  for (const n of NUTRIENTS) food[n] = numberValue(get(n));
  food.portions = [...root.querySelectorAll(".foodform .portion")].map((row) => ({
    name: row.querySelector('[data-portion="name"]').value.trim(),
    grams: numberValue(row.querySelector('[data-portion="grams"]')),
  }));
  if (!food.name || REQUIRED_NUTRIENTS.some((n) => food[n] == null || food[n] < 0)) return { food, error: "error_required" };
  if (OPTIONAL_NUTRIENTS.some((n) => food[n] != null && food[n] < 0)) return { food, error: "error_required" };
  const filled = food.portions.filter((p) => p.name || p.grams != null);
  if (filled.some((p) => !p.name || !(p.grams > 0))) return { food, error: "error_portion" };
  return { food: { ...food, portions: filled }, error: null };
}

// Barcodes: Open Food Facts lookups, and scanning.

const OFF_URL = "https://world.openfoodfacts.org/api/v2/product/";
const OFF_FIELDS = "product_name,brands,nutriments,serving_quantity";
const BARCODE = /^\d{8,14}$/;
const SCAN_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"];
const SCAN_EVERY_MS = 250;

// An Open Food Facts product as a food for the form. Nutrients it lacks are
// null, and a serving size becomes a portion called `serving`.
function offFood(code, product, serving) {
  const n = product.nutriments ?? {};
  const value = (key) => {
    const raw = n[`${key}_100g`];
    const v = Number(raw);
    return raw === "" || raw == null || !Number.isFinite(v) ? null : Math.round(v * 100) / 100;
  };
  let kcal = value("energy-kcal");
  // Some products only give energy in kJ.
  if (kcal == null && value("energy") != null) kcal = Math.round(value("energy") / 4.184);
  const name = [product.product_name?.trim(), firstBrand(product.brands)].filter(Boolean).join(" – ");
  const grams = Number(product.serving_quantity);
  return {
    name,
    barcode: code,
    kcal,
    protein: value("proteins"),
    carbs: value("carbohydrates"),
    fat: value("fat"),
    fibre: value("fiber"),
    sugar: value("sugars"),
    saturated_fat: value("saturated-fat"),
    salt: value("salt"),
    portions: grams > 0 ? [{ name: serving, grams }] : [],
  };
}

// The product with this barcode on Open Food Facts as a food, or null if it
// has none. Throws if Open Food Facts cannot be reached.
async function lookUpBarcode(code, serving, fetchImpl = fetch) {
  const response = await fetchImpl(`${OFF_URL}${encodeURIComponent(code)}.json?fields=${OFF_FIELDS}`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = await response.json();
  return body.status === 1 && body.product ? offFood(code, body.product, serving) : null;
}

// `form` with what `found` knows: its nutrients, its name if the form has
// none, and its portions if the form has none.
function mergeFood(form, found) {
  const merged = { ...form, barcode: found.barcode };
  for (const n of NUTRIENTS) if (found[n] != null) merged[n] = found[n];
  if (!form.name) merged.name = found.name;
  if (!form.portions?.length) merged.portions = found.portions;
  return merged;
}

// Open Food Facts search by name. Browsers cannot reach its search service,
// so the integration asks it, for products with kcal, protein, carbs and fat.

// Open Food Facts' code for a card's language: pt-BR searches as pt.
const offLanguage = (locale) => locale.split("-")[0].toLowerCase();

// The first brand of a search's list, or of a lookup's comma-separated text.
const firstBrand = (brands) => (Array.isArray(brands) ? brands : (brands ?? "").split(","))[0]?.trim() || null;

// A product's name in `lang` if it has one, else in English, else in its own language.
const offName = (product, lang) =>
  [product[`product_name_${lang}`], product.product_name_en, product.product_name].map((n) => n?.trim()).find(Boolean) ?? "";

// A product a search found, as a food. The search has no serving sizes.
const searchedFood = (product, lang, serving) => offFood(product.code, { ...product, product_name: offName(product, lang) }, serving);

function offRowHTML(product, lang, locale, t) {
  const details = [firstBrand(product.brands), product.quantity?.trim()].filter(Boolean).join(" · ");
  return `<button class="row" data-action="off-pick" data-code="${esc(product.code)}">
    <span>${esc(offName(product, lang) || product.code)}${details ? ` <small>${esc(details)}</small>` : ""}</span>
    <small class="num">${esc(fill(t.per_100g_value, { kcal: number(product.nutriments["energy-kcal_100g"], locale) }))}</small></button>`;
}

// What goes under the saved foods a card found for `query`: a button to
// search Open Food Facts for it, then that search, from `off`. A search for
// other text than the query is out of date, so the button shows instead.
// A barcode has its own lookup, and an empty query gets a hint.
function offSearchHTML(query, off, lang, locale, t) {
  const text = query.trim();
  if (!text) return `<div class="muted">${esc(t.off_hint)}</div>`;
  if (BARCODE.test(text)) return "";
  if (off?.query !== text) return `<button class="text" data-action="off-search">${esc(fill(t.off_search, { query: text }))}</button>`;
  let end = "";
  if (off.busy) end = `<div class="muted">${esc(t.off_searching)}</div>`;
  else if (off.error != null) {
    end = `<div class="error">${esc(fill(t.off_search_failed, { message: off.error }))}</div>
      <button class="text" data-action="off-next">${esc(t.try_again)}</button>`;
  } else if (!off.products.length) end = `<div class="muted">${esc(fill(t.off_no_results, { query: text }))}</div>`;
  else if (off.more) end = `<button class="text" data-action="off-next">${esc(t.more)}</button>`;
  return `<div class="sub">${esc(t.off_results)}</div>${off.products.map((p) => offRowHTML(p, lang, locale, t)).join("")}${end}`;
}

// Scan with the Home Assistant app's own scanner. Resolves to the code, or
// null if cancelled. The frontend has no public hook for scan results, so
// this wraps its handler for messages from the app, which still runs and
// acknowledges each one.
function scanWithApp(external, t) {
  return new Promise((resolve) => {
    const original = external.receiveMessage;
    const finish = (code) => {
      external.receiveMessage = original;
      resolve(code);
    };
    external.receiveMessage = function (message) {
      original.call(this, message);
      if (message.type !== "command") return;
      if (message.command === "bar_code/scan_result") {
        external.fireMessage({ type: "bar_code/close" });
        finish(message.payload.rawValue);
      } else if (message.command === "bar_code/aborted") {
        finish(null);
      }
    };
    external.fireMessage({ type: "bar_code/scan", payload: { title: t.scan_title, description: t.scan_description } });
  });
}

// Scan with the browser's barcode reader and the camera, shown in `box`.
// Resolves to the code, or null once `signal` aborts.
async function scanWithCamera(box, t, signal) {
  const supported = await BarcodeDetector.getSupportedFormats();
  const detector = new BarcodeDetector({ formats: SCAN_FORMATS.filter((f) => supported.includes(f)) });
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
  box.hidden = false;
  box.innerHTML = `<video playsinline muted></video>
    <div class="actions"><span class="sub">${esc(t.scanning)}</span><button class="text" data-action="stop-scan">${esc(t.cancel)}</button></div>`;
  const video = box.querySelector("video");
  try {
    video.srcObject = stream;
    await video.play();
    while (!signal.aborted) {
      const codes = await detector.detect(video);
      if (codes.length) return codes[0].rawValue;
      await new Promise((r) => setTimeout(r, SCAN_EVERY_MS));
    }
    return null;
  } finally {
    for (const track of stream.getTracks()) track.stop();
    box.innerHTML = "";
    box.hidden = true;
  }
}

// Which scanner this device offers: the app's, the browser's, or none.
function scannerFor(hass, win = window) {
  if (hass.auth?.external?.config?.hasBarCodeScanner) return "app";
  if ("BarcodeDetector" in win && win.navigator?.mediaDevices?.getUserMedia) return "camera";
  return null;
}

const barcodeError = (err) => (err?.code === "barcode_taken" ? "error_barcode_taken" : "error_failed");
