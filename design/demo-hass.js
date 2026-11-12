// A Home Assistant for the cards to run in without one, for the design
// system's live previews; design/build.js packs it with the cards' bundle.
//
// Its websocket commands answer from sample data in memory, with the results,
// errors and change events that websocket.py, data.py and db.py give. The
// sample data is tests/e2e/screenshots.py's, for the people tests/e2e/conftest.py
// sets up. The Home Assistant app's barcode scanner reads DEMO_BARCODE, and
// Open Food Facts, searched or looked up by barcode, knows DEMO_PRODUCTS.

const TIME_ZONE = "Europe/London";
const MEALS = ["breakfast", "lunch", "dinner", "snacks"];
const NUTRIENTS = ["kcal", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat", "salt"];
const REQUIRED_NUTRIENTS = NUTRIENTS.slice(0, 4);
const MIN_KG = 20;
const MAX_KG = 400;
const MAX_RANGE = 400;
const SEARCH_PAGE_SIZE = 10;
const DAY_MS = 86_400_000;
// How long the app's scanner takes to read a barcode.
const SCAN_MS = 300;

// What the app's scanner reads: a product Open Food Facts knows and no saved
// food has, until someone saves it.
const DEMO_BARCODE = "5201054017111";

// Days

// The ISO day it is at `ms` in Home Assistant's time zone.
const dayAt = (ms) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(ms);

const addDays = (day, days) => new Date(Date.parse(day) + days * DAY_MS).toISOString().slice(0, 10);

const daysFrom = (start, end) => Math.round((Date.parse(end) - Date.parse(start)) / DAY_MS);

// Whether `text` is a real day, as "2026-11-11".
function isDay(text) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const ms = Date.parse(text);
  return !Number.isNaN(ms) && new Date(ms).toISOString().startsWith(text);
}

// The time as the database records it, in UTC to the second.
const timestamp = (ms) => `${new Date(ms).toISOString().slice(0, 19)}+00:00`;

// Python

// Python's round() of a number to `digits` (0 or 1) decimals. toFixed rounds
// the exact binary value as Python does, except for an exact tie, which it
// rounds up and Python to even. To one decimal only x.25 and x.75 are ties.
function pyRound(x, digits = 0) {
  const halves = digits ? x * 4 : x * 2;
  if (Number.isInteger(halves) && halves % 2) {
    const low = Math.floor(x * 10 ** digits);
    return (low % 2 ? low + 1 : low) / 10 ** digits;
  }
  return Number(x.toFixed(digits));
}

// Python's repr() of a value from JSON, as error messages quote it.
function pyRepr(value) {
  if (value == null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "string") {
    const escaped = value.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t");
    if (value.includes("'") && !value.includes('"')) return `"${escaped}"`;
    return `'${escaped.replace(/'/g, "\\'")}'`;
  }
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(", ")}]`;
  if (typeof value === "object") return `{${Object.entries(value).map(([k, v]) => `${pyRepr(k)}: ${pyRepr(v)}`).join(", ")}}`;
  return String(value);
}

const pyStr = (value) => (typeof value === "string" ? value : pyRepr(value));

// Python's float(), which the integration's validators call. What it cannot
// take at all raises a TypeError, which Home Assistant answers as an unknown
// error.
function pyFloat(value) {
  if (typeof value === "number" || typeof value === "boolean") return Number(value);
  if (typeof value !== "string") throw new TypeError("float() argument must be a string or a real number");
  if (!/^\s*[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?\s*$/i.test(value)) {
    throw new Invalid(`not a valid value: could not convert string to float: ${pyRepr(value)}`);
  }
  return Number(value);
}

// Validation, as websocket.py's schemas do it with probatio

// A value a schema refuses. Home Assistant answers with invalid_format, and
// with what probatio's humanize_error says.
class Invalid extends Error {}

const wsError = (code, message) => ({ code, message });

// An error whose details the cards read, which websocket.py sends in its
// translation placeholders.
const detailedError = (code, message, details) => ({
  code,
  message,
  translation_key: code,
  translation_placeholders: details,
  translation_domain: "metron",
});
const NOT_FOUND = wsError("not_found", "Not found");
const MEAL_CHANGED = wsError("meal_changed", "The meal was changed or deleted meanwhile");

// probatio's line for one error: what, where, and the value it got.
function problem(message, path, value) {
  let got = pyRepr(value);
  if (got.length > 500) got = `${got.slice(0, 497)}...`;
  return `${message} at '${path}'. Got ${got}`;
}

// Each validator takes a value, and the store for those that need today,
// and returns what it accepts or throws Invalid.

const text = (value) => {
  if (typeof value !== "string") throw new Invalid("expected str");
  return value;
};

const integer = (value) => {
  if (!Number.isInteger(value)) throw new Invalid("expected int");
  return value;
};

// websocket.py's _day.
const isoDay = (value, store) => {
  const day = pyStr(value);
  if (!isDay(day)) throw new Invalid("not an ISO date");
  if (day > store.today) throw new Invalid("in the future");
  return day;
};

// websocket.py's _non_negative, _positive, _name and _language.
const nonNegative = (value) => {
  const number = pyFloat(value);
  if (number < 0) throw new Invalid("negative");
  return number;
};

const positive = (value) => {
  const number = pyFloat(value);
  if (number <= 0) throw new Invalid("not positive");
  return number;
};

const name = (value) => {
  const trimmed = pyStr(value).trim();
  if (!trimmed) throw new Invalid("empty");
  return trimmed;
};

const language = (value) => {
  const code = pyStr(value);
  if (!/^[a-z]{2,3}$/.test(code)) throw new Invalid("not a two- or three-letter language code");
  return code;
};

// vol.Any(None, check), which gives none of check's own messages.
const orNone = (check) => (value, store) => {
  if (value === null) return null;
  try {
    return check(value, store);
  } catch (err) {
    if (err instanceof Invalid) throw new Invalid("not a valid value");
    throw err;
  }
};

const oneOf = (values) => (value) => {
  if (!values.includes(value)) throw new Invalid(`value must be one of ${pyRepr([...values].sort())}`);
  return value;
};

const between = (check, min, max) => (value, store) => {
  const number = check(value, store);
  if (min != null && number < min) throw new Invalid(`value must be at least ${min}`);
  if (max != null && number > max) throw new Invalid(`value must be at most ${max}`);
  return number;
};

const boolean = (value) => {
  if (typeof value !== "boolean") throw new Invalid("expected bool");
  return value;
};

// vol.All([int], vol.Length(min=1)).
const idList = (value) => {
  if (!Array.isArray(value)) throw new Invalid("expected a list");
  if (!value.length) throw new Invalid("length of value must be at least 1");
  return value.map(integer);
};

// websocket.py's MEAL_ITEMS: a saved food's id and grams, or fixed values
// with a name and kcal; at least one.
function mealItems(value, store, path, errors) {
  if (!Array.isArray(value)) throw new Invalid("expected a list");
  if (!value.length) throw new Invalid("length of value must be at least 1");
  return value.map((item, i) => {
    const where = `${path}[${i}]`;
    if (item === null || typeof item !== "object" || Array.isArray(item)) {
      errors.push(problem("expected a mapping", where, item));
      return item;
    }
    const schema = "food_id" in item ? FOOD_ITEM : FIXED_ITEM;
    const found = [];
    const out = validate(schema, item, where, found, store);
    if (found.length) errors.push(problem("not a valid value", where, item));
    return out;
  });
}

// vol.Coerce(float).
const coerceFloat = (value) => {
  try {
    return pyFloat(value);
  } catch {
    throw new Invalid("expected float");
  }
};

const required = (check) => ({ required: true, check });
const optional = (check, ...fallback) => (fallback.length ? { check, fallback: fallback[0] } : { check });

const PORTION = { name: required(name), grams: required(positive) };

// websocket.py's PORTIONS: a list of {name, grams}. Its errors go in
// `errors` with their place in the list.
function portionList(value, store, path, errors) {
  if (!Array.isArray(value)) throw new Invalid("expected a list");
  return value.map((item, i) => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) {
      errors.push(problem("expected a mapping", `${path}[${i}]`, item));
      return item;
    }
    return validate(PORTION, item, `${path}[${i}]`, errors, store);
  });
}

// `data` as `schema` accepts it, with defaults filled in. Each error goes in
// `errors`, as probatio would report it.
function validate(schema, data, where, errors, store) {
  const at = (key) => (where ? `${where}.${key}` : key);
  const out = {};
  for (const [key, value] of Object.entries(data)) {
    const field = schema[key];
    if (!field) {
      errors.push(problem("not a valid option", at(key), value));
      continue;
    }
    try {
      out[key] = field.check(value, store, at(key), errors);
    } catch (err) {
      if (!(err instanceof Invalid)) throw err;
      errors.push(problem(err.message, at(key), value));
    }
  }
  for (const [key, field] of Object.entries(schema)) {
    if (key in data) continue;
    if (field.required) errors.push(problem("required key not provided", at(key), null));
    else if ("fallback" in field) out[key] = field.fallback;
  }
  return out;
}

const PERSON = { person: required(text) };
const NUTRIENT_FIELDS = Object.fromEntries(NUTRIENTS.map((n) => [n, optional(orNone(nonNegative))]));
const FOOD_FIELDS = { barcode: optional(orNone(name)), portions: optional(portionList), ...NUTRIENT_FIELDS };
const FOOD_ITEM = { food_id: required(integer), grams: required(positive) };
const FIXED_ITEM = { name: required(name), grams: optional(orNone(positive)), ...NUTRIENT_FIELDS, kcal: required(nonNegative) };

// Each command's schema, after its type, and the DemoStore method that runs it.
const COMMANDS = {
  "metron/people": [{}, "_listPeople"],
  "metron/subscribe": [{}, "_subscribed"],
  "metron/day": [{ ...PERSON, day: required(isoDay) }, "_day"],
  "metron/days": [{ ...PERSON, start: required(isoDay), end: required(isoDay) }, "_days"],
  "metron/entry/add": [
    {
      ...PERSON,
      day: required(isoDay),
      meal: required(oneOf(MEALS)),
      food_id: optional(integer),
      grams: optional(positive),
      name: optional(name),
      ...NUTRIENT_FIELDS,
    },
    "_addEntry",
  ],
  "metron/entry/update": [
    {
      entry_id: required(integer),
      day: optional(isoDay),
      meal: optional(oneOf(MEALS)),
      grams: optional(positive),
      name: optional(name),
      ...NUTRIENT_FIELDS,
    },
    "_updateEntry",
  ],
  "metron/entry/delete": [{ entry_id: required(integer) }, "_deleteEntry"],
  "metron/meal/copy": [
    {
      ...PERSON,
      from_day: required(isoDay),
      from_meal: required(oneOf(MEALS)),
      to_day: required(isoDay),
      to_meal: required(oneOf(MEALS)),
    },
    "_copyMeal",
  ],
  "metron/food/search": [{ query: required(text), limit: optional(between(integer, 1, 100), 20) }, "_searchFoods"],
  "metron/food/recent": [{ ...PERSON, limit: optional(between(integer, 1, 100), 10) }, "_recentFoods"],
  "metron/food/barcode": [{ barcode: required(name) }, "_foodByBarcode"],
  "metron/food/add": [
    { name: required(name), ...FOOD_FIELDS, person: optional(text), anyway: optional(boolean, false) },
    "_addFood",
  ],
  "metron/food/meals": [{ food_id: required(integer) }, "_foodMeals"],
  "metron/meals": [{ person: optional(text) }, "_listMeals"],
  "metron/meal/add": [{ name: required(name), owner: required(orNone(text)), items: required(mealItems) }, "_addMeal"],
  "metron/meal/update": [
    {
      meal_id: required(integer),
      version: required(integer),
      name: optional(name),
      owner: optional(orNone(text)),
      items: optional(mealItems),
    },
    "_updateMeal",
  ],
  "metron/meal/delete": [{ meal_id: required(integer), version: required(integer) }, "_deleteMeal"],
  "metron/meal/log": [
    {
      ...PERSON,
      day: required(isoDay),
      meal: required(oneOf(MEALS)),
      meal_id: required(integer),
      version: required(integer),
      items: required(idList),
    },
    "_logMeal",
  ],
  "metron/food/update": [{ food_id: required(integer), name: optional(name), ...FOOD_FIELDS }, "_updateFood"],
  "metron/food/delete": [{ food_id: required(integer) }, "_deleteFood"],
  "metron/openfoodfacts/search": [
    { query: required(name), language: required(language), page: optional(between(integer, 1), 1) },
    "_searchOpenFoodFacts",
  ],
  "metron/weights": [{ ...PERSON, start: optional(isoDay, "0001-01-01"), end: optional(isoDay) }, "_listWeights"],
  "metron/weight/set": [
    { ...PERSON, day: required(isoDay), kg: required(between(coerceFloat, MIN_KG, MAX_KG)) },
    "_setWeight",
  ],
  "metron/weight/delete": [{ ...PERSON, day: required(isoDay) }, "_deleteWeight"],
};

// Goals, as goals.py works them out

const ACTIVITY = { sedentary: 1.2, light: 1.375, moderate: 1.55, active: 1.725, very_active: 1.9 };
const KG_PER_LB = 0.45359237;
const PACES = {
  lose_0_75: -0.75,
  lose_1_5_lb: -1.5 * KG_PER_LB,
  lose_0_5: -0.5,
  lose_1_lb: -1 * KG_PER_LB,
  lose_0_25: -0.25,
  lose_0_5_lb: -0.5 * KG_PER_LB,
  maintain: 0.0,
};
const KCAL_PER_KG = 7700;

const ageOn = (birth, day) => Number(day.slice(0, 4)) - Number(birth.slice(0, 4)) - (day.slice(5) < birth.slice(5) ? 1 : 0);

// Mifflin-St Jeor, for `person` at `weightKg` on `day`.
const restingBurn = (person, weightKg, day) =>
  10 * weightKg + 6.25 * person.height_cm - 5 * ageOn(person.birth_date, day) + (person.sex === "male" ? 5 : -161);

// The day's goals, with the fields and rounding of data.py's async_refresh_goals:
// the goal without activity, plus the `added` kcal activity added that day.
function goalsFor(person, weightKg, day, added = 0) {
  const burn = restingBurn(person, weightKg, day) * ACTIVITY[person.activity];
  const kcal = pyRound((person.calorie_goal ?? burn + (PACES[person.pace] * KCAL_PER_KG) / 7) + added);
  const grams = (pct, perGram) => pyRound((kcal * pct) / 100 / perGram, 1);
  return { kcal, protein: grams(person.protein_pct, 4), carbs: grams(person.carbs_pct, 4), fat: grams(person.fat_pct, 9) };
}

// What `measured` kcal of activity add to the goal of `person`, at
// `weightKg` on `day`, by goals.py's activity_counted, activity_allowed and
// activity_added: the share of it that counts, to the nearest 10 kcal as
// Python's round(x, -1) has it and at most the cap; what the activity level
// already allows for; and what goes beyond that.
function activityFor(person, weightKg, day, { measured, share, cap }) {
  const counted = Math.max(0, Math.min(cap, pyRound((measured * share) / 100 / 10) * 10));
  const allowed = restingBurn(person, weightKg, day) * (ACTIVITY[person.activity] - 1.2);
  return { counted, allowed, added: Math.max(0, counted - allowed) };
}

const bandLimits = (heightCm) => {
  const square = (heightCm / 100) ** 2;
  return {
    underweight_below_kg: pyRound(18.5 * square, 1),
    overweight_from_kg: pyRound(25.0 * square, 1),
    obese_from_kg: pyRound(30.0 * square, 1),
  };
};

// Sample data

const DEMO_USER = {
  id: "8d1c3e5a7b9f4d2e8a6c4b2e0f1a3c5d",
  name: "Debora",
  is_owner: true,
  is_admin: true,
  credentials: [{ auth_provider_type: "homeassistant", auth_provider_id: null }],
  mfa_modules: [],
};

// tests/e2e/conftest.py's PERSON_FORMS, with person entities, Debora's
// linked to DEMO_USER, so a card with no person shows hers.
const PEOPLE = [
  {
    key: "3f2a9c1e5b7d4f6a8c0e2b4d6f8a1c3e",
    name: "Matteo",
    person_entity: "person.matteo",
    user_id: "e4b6d8f0a2c4e6b8d0f2a4c6e8b0d2f4",
    sex: "male",
    birth_date: "1990-06-01",
    height_cm: 180,
    start_weight_kg: 95,
    start_date: "2025-11-01",
    goal_weight_kg: 82,
    activity: "light",
    pace: "lose_0_5",
    calorie_goal: null,
    protein_pct: 25,
    carbs_pct: 45,
    fat_pct: 30,
    active_calories_enabled: false,
    active_calories_entity: null,
    active_calories_share: 75,
    active_calories_cap: 1500,
  },
  {
    key: "7b5d3f1a9c8e4a2b6d0f8e6c4a2b0d9f",
    name: "Debora",
    person_entity: "person.debora",
    user_id: DEMO_USER.id,
    sex: "female",
    birth_date: "1996-03-15",
    height_cm: 165,
    start_weight_kg: 70,
    start_date: "2026-11-01",
    goal_weight_kg: 62,
    activity: "moderate",
    pace: "lose_0_5",
    calorie_goal: null,
    protein_pct: 20,
    carbs_pct: 50,
    fat_pct: 30,
    active_calories_enabled: true,
    active_calories_entity: "sensor.garmin_connect_active_calories",
    active_calories_share: 75,
    active_calories_cap: 1500,
  },
];

// The active calories Debora's watch measured, as [days before today, kcal];
// an automation logged the day marked "action" instead, through the Log
// active calories action. Between them the days add to her goal, stay within
// her activity level, and pass the daily limit. Earlier days have none.
const SAMPLE_ACTIVITY = [
  [0, 880],
  [1, 1240],
  [2, 520],
  [3, 2300],
  [4, 700, "action"],
  [5, 960],
];

// tests/e2e/screenshots.py's FOODS: per 100 g, with the grams Debora ate
// of each today, by meal.
const SAMPLE_FOODS = [
  ["Porridge oats", 389, 16.9, 66, 6.9, [["Bowl", 40]], "breakfast", 60],
  ["Greek yogurt 2%", 73, 10, 3.6, 2, [["Pot", 170]], "breakfast", 170],
  ["Banana", 89, 1.1, 23, 0.3, [["Medium", 120]], "breakfast", 120],
  ["Chicken breast, grilled", 165, 31, 0, 3.6, [], "lunch", 150],
  ["Basmati rice, cooked", 130, 2.7, 28, 0.3, [], "lunch", 180],
  ["Broccoli", 34, 2.8, 7, 0.4, [], "lunch", 120],
  ["Olive oil", 884, 0, 0, 100, [["Tablespoon", 13.5]], "lunch", 10],
  ["Almonds", 579, 21, 22, 50, [["Handful", 25]], "snacks", 25],
  ["Salmon fillet", 208, 20, 0, 13, [], null, null],
  ["Wholemeal bread", 247, 13, 41, 3.4, [["Slice", 36]], null, null],
];

// Saved meals, as screenshots.py's add_sample_data saves them: a name, its
// owner, and its items, each the index of a SAMPLE_FOODS food and grams, or
// fixed values.
const SAMPLE_MEALS = [
  ["Porridge with banana", null, [[0, 60], [2, 120]]],
  ["Chicken and rice", "debora", [[3, 150], [4, 180], [5, 120]]],
  ["Post-workout shake", "matteo", [[2, 120], [{ name: "Whey protein", grams: 30, kcal: 120, protein: 24, fat: 2 }]]],
];

// Open Food Facts

const nutriments = (kcal, proteins, carbohydrates, fat, more = {}) => ({
  "energy-kcal_100g": kcal,
  energy_100g: Math.round(kcal * 4.184),
  proteins_100g: proteins,
  carbohydrates_100g: carbohydrates,
  fat_100g: fat,
  ...Object.fromEntries(Object.entries(more).map(([key, value]) => [`${key}_100g`, value])),
});

// Open Food Facts' products: what its search gives of each (names, brands
// as a list, quantity and nutriments) and the serving size a lookup adds.
// More than a page of them match "greek yogurt".
const DEMO_PRODUCTS = [
  {
    code: "5201054025321",
    product_name: "Total 0% Greek yogurt",
    brands: ["Fage"],
    quantity: "500 g",
    serving_quantity: 170,
    nutriments: nutriments(54, 10.3, 3, 0, { sugars: 3, "saturated-fat": 0, salt: 0.1 }),
  },
  {
    code: "5201054017111",
    product_name: "Total 5% Greek yogurt",
    brands: ["Fage"],
    quantity: "170 g",
    serving_quantity: 170,
    nutriments: nutriments(93, 9, 3, 5, { sugars: 3, "saturated-fat": 3.2, salt: 0.1 }),
  },
  {
    code: "5201054017081",
    product_name: "Total 2% Greek yogurt",
    brands: ["Fage"],
    quantity: "170 g",
    serving_quantity: 170,
    nutriments: nutriments(73, 10, 3.6, 2, { sugars: 3.6, "saturated-fat": 1.3, salt: 0.1 }),
  },
  {
    code: "5051413908606",
    product_name: "Greek style natural yogurt",
    brands: ["Yeo Valley"],
    quantity: "450 g",
    nutriments: nutriments(115, 5.4, 4.9, 8.1, { sugars: 4.9, "saturated-fat": 5.3, salt: 0.15 }),
  },
  {
    code: "0894700010137",
    product_name: "Nonfat Greek yogurt",
    brands: ["Chobani"],
    quantity: "150 g",
    serving_quantity: 150,
    nutriments: nutriments(53, 10, 3.6, 0, { sugars: 3.3, "saturated-fat": 0, salt: 0.09 }),
  },
  {
    code: "0818290014269",
    product_name: "Whole milk plain Greek yogurt",
    brands: ["Chobani"],
    quantity: "907 g",
    serving_quantity: 170,
    nutriments: nutriments(94, 8.8, 4.4, 4.4, { sugars: 3.5, "saturated-fat": 2.9, salt: 0.1 }),
  },
  {
    code: "5000436589884",
    product_name: "Greek style natural yogurt",
    brands: ["Tesco"],
    quantity: "500 g",
    nutriments: nutriments(132, 4.5, 5.7, 10.2, { sugars: 5.7, "saturated-fat": 6.6, salt: 0.13 }),
  },
  {
    code: "4056489193216",
    product_name: "Greek style yogurt",
    brands: ["Milbona"],
    quantity: "500 g",
    nutriments: nutriments(122, 3.9, 4.3, 10, { sugars: 4.3, "saturated-fat": 6.5, salt: 0.1 }),
  },
  {
    code: "8017596079480",
    product_name: "Yogurt greco bianco",
    product_name_it: "Yogurt greco bianco",
    product_name_en: "Greek white yogurt",
    brands: ["Land", " Eurospin"],
    quantity: "150g",
    serving_quantity: 150,
    nutriments: nutriments(70, 9, 4, 2, { sugars: 4, salt: 0.18 }),
  },
  {
    code: "3033491442118",
    product_name: "Oikos Greek style natural yogurt",
    brands: ["Danone"],
    quantity: "4 x 110 g",
    serving_quantity: 110,
    nutriments: nutriments(106, 3.7, 4.6, 8.1, { sugars: 4.6, "saturated-fat": 5.4, salt: 0.12 }),
  },
  {
    code: "4061458000312",
    product_name: "Griechischer Joghurt 10% Fett",
    product_name_de: "Griechischer Joghurt 10% Fett",
    product_name_en: "Greek yogurt 10% fat",
    brands: ["Milsani"],
    quantity: "500 g",
    nutriments: nutriments(122, 4, 4, 10, { sugars: 4, "saturated-fat": 6.8, salt: 0.11 }),
  },
  {
    code: "0052159700010",
    product_name: "Plain 0% Greek nonfat yogurt",
    brands: ["Oikos"],
    quantity: "32 oz",
    serving_quantity: 170,
    nutriments: nutriments(57, 10.6, 4, 0, { sugars: 3.5, "saturated-fat": 0, salt: 0.1 }),
  },
  {
    code: "5000128976435",
    product_name: "Greek style yogurt with honey",
    brands: ["Co-op"],
    quantity: "450 g",
    nutriments: nutriments(141, 4.4, 12.4, 8.2, { sugars: 12.4, "saturated-fat": 5.3, salt: 0.12 }),
  },
  {
    code: "5000168001142",
    product_name: "Porridge oats",
    brands: ["Quaker"],
    quantity: "1 kg",
    serving_quantity: 40,
    nutriments: nutriments(375, 11, 60, 8, { fiber: 9, sugars: 1.1, "saturated-fat": 1.5, salt: 0.01 }),
  },
  {
    code: "5060088700048",
    product_name: "Smooth peanut butter",
    brands: ["Whole Earth"],
    quantity: "340 g",
    nutriments: nutriments(622, 25, 13, 51, { fiber: 6.8, sugars: 4.5, "saturated-fat": 9.6, salt: 0.6 }),
  },
  {
    code: "7290011017866",
    product_name: "Classic houmous",
    brands: ["Sabra"],
    quantity: "200 g",
    nutriments: nutriments(290, 7.3, 10.5, 24, { fiber: 6, sugars: 0.5, "saturated-fat": 2.2, salt: 1.1 }),
  },
  {
    code: "3046920028004",
    product_name: "Excellence 70% cocoa dark chocolate",
    brands: ["Lindt"],
    quantity: "100 g",
    serving_quantity: 10,
    nutriments: nutriments(566, 9.5, 34, 41, { fiber: 11, sugars: 29, "saturated-fat": 24, salt: 0.02 }),
  },
  {
    code: "8076800195057",
    product_name: "Spaghetti n.5",
    brands: ["Barilla"],
    quantity: "500 g",
    serving_quantity: 80,
    nutriments: nutriments(359, 12.5, 71.2, 2, { fiber: 3, sugars: 3.5, "saturated-fat": 0.5, salt: 0.01 }),
  },
];

// A page of the products whose names or brands hold every word of `query`,
// as openfoodfacts.async_search gives it: names in `language` and English
// where a product has them.
function searchProducts(query, language, page) {
  const words = query.toLowerCase().split(/\s+/);
  const langs = [...new Set([language, "en"])];
  const found = DEMO_PRODUCTS.filter((p) => {
    const haystack = [p.product_name, ...langs.map((l) => p[`product_name_${l}`]), ...p.brands].join(" ").toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
  const products = found.slice((page - 1) * SEARCH_PAGE_SIZE, page * SEARCH_PAGE_SIZE).map((p) => ({
    code: p.code,
    product_name: p.product_name,
    ...Object.fromEntries(langs.filter((l) => p[`product_name_${l}`]).map((l) => [`product_name_${l}`, p[`product_name_${l}`]])),
    brands: p.brands,
    quantity: p.quantity,
    nutriments: p.nutriments,
  }));
  return { products, more: page < Math.ceil(found.length / SEARCH_PAGE_SIZE) };
}

const OFF_PRODUCT = /^https:\/\/world\.openfoodfacts\.org\/api\/v2\/product\/([^/?#]+)\.json/;

// `realFetch`, except that Open Food Facts' product API answers from
// DEMO_PRODUCTS, as it would with the fields the cards ask for, and with a
// 404 for a barcode it does not know.
function demoFetch(realFetch) {
  return async (input, init) => {
    const url = typeof input === "string" ? input : (input?.url ?? String(input));
    const match = OFF_PRODUCT.exec(url);
    if (!match) return realFetch(input, init);
    const code = decodeURIComponent(match[1]);
    const p = DEMO_PRODUCTS.find((product) => product.code === code);
    const body = p
      ? {
          code,
          product: {
            brands: p.brands.join(","),
            nutriments: p.nutriments,
            product_name: p.product_name,
            ...(p.serving_quantity ? { serving_quantity: p.serving_quantity } : {}),
          },
          status: 1,
          status_verbose: "product found",
        }
      : { code, status: 0, status_verbose: "product not found" };
    return new Response(JSON.stringify(body), { status: p ? 200 : 404, headers: { "Content-Type": "application/json" } });
  };
}

// The store

// What crosses the websocket: JSON, so nothing is shared with the caller.
const wire = (value) => (value === undefined ? null : JSON.parse(JSON.stringify(value)));

const personJSON = (p) => ({
  id: p.key,
  name: p.name,
  person_entity: p.person_entity,
  height_cm: p.height_cm,
  start_weight_kg: p.start_weight_kg,
  start_date: p.start_date,
  goal_weight_kg: p.goal_weight_kg,
  ...bandLimits(p.height_cm),
});

// metron/day's activity, from a day's stored row: with a status if the day
// is `today`, else null. The demo's sensor is always there, with a reading
// from today that counts, so today is capped, within the level or counting.
function activityJSON({ source, measured, counted, added, allowed, share, cap }, today) {
  let status = null;
  if (today) status = (measured * share) / 100 > cap ? "capped" : counted <= allowed ? "level" : "counting";
  return { source, measured, counted, added, allowed, share, cap, status };
}

const byDay = ([a], [b]) => (a < b ? -1 : a > b ? 1 : 0);

// The integration's data and websocket commands, in memory, on sample data
// dated from the day it is seeded on. `now` gives the time in ms, which sets
// today.
class DemoStore {
  constructor(now) {
    this._now = now;
    this._listeners = new Set();
    this._events = null;
    this._seed();
  }

  // Today in Home Assistant's time zone.
  get today() {
    return dayAt(this._now());
  }

  // Answers `message` as Home Assistant's callWS would: a moment later, with
  // the result or rejecting with {code, message}, after the change events
  // the command sent.
  call(message) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        const events = [];
        this._events = events;
        let settle;
        try {
          const result = wire(this._handle(wire(message)));
          settle = () => resolve(result);
        } catch (err) {
          if (err instanceof Error) console.error("Metron demo: error handling message", message, err);
          settle = () => reject(err instanceof Error ? wsError("unknown_error", "Unknown error") : err);
        }
        this._events = null;
        for (const event of events) this._send(event);
        settle();
      });
    });
  }

  // hass.connection.subscribeMessage: `callback` gets each change event
  // until the function it resolves to is called.
  async subscribeMessage(callback, message) {
    await this.call(message);
    this._listeners.add(callback);
    return async () => {
      this._listeners.delete(callback);
    };
  }

  // Puts the sample data back, dated from today, and tells every subscriber
  // that everything changed.
  reset() {
    this._seed();
    setTimeout(() => {
      for (const p of this._people) this._send({ person: p.key, days: [] });
      this._send({ person: null, days: [] });
    });
  }

  _send(event) {
    for (const listener of [...this._listeners]) listener(wire(event));
  }

  // data.py's _changed: after a write, {person, days}, with person null for
  // saved foods and days the days whose entries changed.
  _changed(person, days = []) {
    this._events?.push({ person, days: [...new Set(days)].sort() });
  }

  _handle(message) {
    const { type, id: _id, ...fields } = message;
    const command = COMMANDS[type];
    if (!command) throw wsError("unknown_command", "Unknown command.");
    const [schema, method] = command;
    const errors = [];
    const msg = validate(schema, fields, "", errors, this);
    if (errors.length) throw wsError("invalid_format", errors.sort().join("\n"));
    let person = null;
    if ("person" in msg) {
      person = this._people.find((p) => p.key === msg.person);
      if (!person) throw wsError("not_found", "No such person");
    }
    return this[method](msg, person);
  }

  _seed() {
    this._people = PEOPLE.map((p) => ({ ...p }));
    this._foods = new Map();
    this._entries = new Map();
    this._weights = new Map(this._people.map((p) => [p.key, new Map()]));
    this._goals = new Map(this._people.map((p) => [p.key, new Map()]));
    this._activity = new Map(this._people.map((p) => [p.key, new Map()]));
    this._meals = new Map();
    this._nextFood = 1;
    this._nextEntry = 1;
    this._nextMeal = 1;
    this._nextItem = 1;
    const today = this.today;
    this.seededOn = today;
    const [matteo, debora] = this._people.map((p) => p.key);
    const run = (message) => this._handle(message);
    const { active_calories_entity: sensor, active_calories_share: share, active_calories_cap: cap } = this._people[1];
    for (const [daysAgo, measured, source = sensor] of SAMPLE_ACTIVITY) {
      this._activity.get(debora).set(addDays(today, -daysAgo), { source, measured, share, cap });
    }
    const foods = [];
    // As tests/e2e/screenshots.py's add_sample_data adds it, through the
    // same commands, in the same order.
    for (const [foodName, kcal, protein, carbs, fat, portions, meal, grams] of SAMPLE_FOODS) {
      const food = run({
        type: "metron/food/add",
        name: foodName,
        kcal,
        protein,
        carbs,
        fat,
        portions: portions.map(([n, g]) => ({ name: n, grams: g })),
        person: debora,
      });
      foods.push(food);
      if (meal) run({ type: "metron/entry/add", person: debora, day: today, meal, food_id: food.id, grams });
    }
    for (const [mealName, owner, items] of SAMPLE_MEALS) {
      const mealItems = items.map(([index, grams]) => (typeof index === "number" ? { food_id: foods[index].id, grams } : index));
      run({ type: "metron/meal/add", name: mealName, owner: owner === "matteo" ? matteo : owner === "debora" ? debora : null, items: mealItems });
    }
    const first = addDays(today, -360);
    for (let n = 0; n <= 360; n += 4) {
      const wobble = (((n * 37) % 11) - 5) / 10;
      run({ type: "metron/weight/set", person: matteo, day: addDays(first, n), kg: pyRound(95 - n * 0.018 + wobble, 1) });
    }
    [69.8, 69.6, 69.7, 69.4, 69.2, 69.3, 69.0, 68.9].forEach((kg, n) => {
      run({ type: "metron/weight/set", person: debora, day: addDays(today, -(28 - n * 4)), kg });
    });
    for (let n = 1; n <= 28; n++) {
      const day = addDays(today, -n);
      const kcals = [380 + ((n * 53) % 120), 560 + ((n * 71) % 220), 620 + ((n * 97) % 330), (n * 31) % 260];
      MEALS.forEach((meal, i) => {
        const kcal = kcals[i];
        run({ type: "metron/entry/add", person: debora, day, meal, name: "Sample", kcal, protein: kcal * 0.05, carbs: kcal * 0.12, fat: kcal * 0.035 });
      });
    }
    // Goals as the integration would have recorded them, refreshing them each
    // midnight and after each weigh-in, had it run since the person's start
    // or their first data, whichever came first.
    for (const p of this._people) {
      this._goals.get(p.key).clear();
      const days = [p.start_date, ...this._weights.get(p.key).keys()];
      for (const e of this._entries.values()) if (e.person === p.key) days.push(e.day);
      for (let day = days.reduce((a, b) => (b < a ? b : a)); day <= today; day = addDays(day, 1)) this._refreshGoals(p, day);
    }
  }

  // Tables, as db.py reads them

  _entryRows(key, test) {
    return [...this._entries.values()].filter((e) => e.person === key && test(e));
  }

  _goalOn(key, day) {
    let found = null;
    for (const [d, goals] of [...this._goals.get(key)].sort(byDay)) if (d <= day) found = goals;
    return found;
  }

  _latestWeight(key, day) {
    const before = [...this._weights.get(key)].filter(([d]) => d <= day).sort(byDay);
    return before.length ? before[before.length - 1][1].kg : null;
  }

  _weightRows(key, start, end) {
    return [...this._weights.get(key)]
      .filter(([d]) => d >= start && d <= end)
      .sort(byDay)
      .map(([day, w]) => ({ day, kg: w.kg }));
  }

  // data.py's async_refresh_goals, for any day: work out what the day's
  // activity adds, and record the day's goals if they differ from those in
  // force.
  _refreshGoals(person, day = this.today) {
    const weight = this._latestWeight(person.key, day) ?? person.start_weight_kg;
    const activity = this._activity.get(person.key).get(day);
    if (activity) Object.assign(activity, activityFor(person, weight, day, activity));
    const goals = goalsFor(person, weight, day, activity?.added);
    const current = this._goalOn(person.key, day);
    if (!current || REQUIRED_NUTRIENTS.some((n) => current[n] !== goals[n])) this._goals.get(person.key).set(day, goals);
  }

  _insertEntry(person, entry) {
    const row = { id: this._nextEntry++, person };
    for (const key of ["day", "meal", "food_id", "name", "grams", ...NUTRIENTS]) row[key] = entry[key] ?? null;
    Object.assign(row, { created_at: timestamp(this._now()), source: null });
    this._entries.set(row.id, row);
    return row;
  }

  _foodRow(id, values, updatedAt, savedBy = null) {
    const row = { id };
    for (const key of ["name", "barcode", ...NUTRIENTS]) row[key] = values[key] ?? null;
    return Object.assign(row, { portions: values.portions ?? [], updated_at: updatedAt, saved_by: savedBy });
  }

  // db.py's _meals: a meal with its items, a saved food's at its values now.
  _mealJSON(meal) {
    const items = meal.items.map((item) => {
      if (item.food_id == null) return { ...item };
      const food = this._foods.get(item.food_id);
      const values = Object.fromEntries(NUTRIENTS.map((n) => [n, food[n] == null ? null : (food[n] * item.grams) / 100]));
      return { id: item.id, food_id: item.food_id, grams: item.grams, name: food.name, ...values };
    });
    return { id: meal.id, owner: meal.owner || null, name: meal.name, version: meal.version, items };
  }

  // Meals `test` picks, A to Z as db.py orders them.
  _mealRows(test) {
    const order = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
    return [...this._meals.values()]
      .filter(test)
      .sort((a, b) => order(a.name.toLowerCase(), b.name.toLowerCase()) || a.id - b.id)
      .map((m) => this._mealJSON(m));
  }

  // db.py's _clash: the owner of a meal called `name` that someone who sees
  // `owner`'s meals sees, or null.
  _clash(owner, name, exclude = null) {
    const folded = name.toLowerCase();
    const clashes = [...this._meals.values()].filter(
      (m) => m.name.toLowerCase() === folded && m.id !== exclude && (owner === "" || m.owner === "" || m.owner === owner),
    );
    if (!clashes.length) return null;
    return clashes.some((m) => m.owner === "") ? "" : clashes[0].owner;
  }

  _mealItems(items) {
    return items.map((item) => {
      if ("food_id" in item) {
        if (!this._foods.has(item.food_id)) throw NOT_FOUND;
        return { id: this._nextItem++, food_id: item.food_id, grams: item.grams };
      }
      const fixed = { id: this._nextItem++, food_id: null, name: item.name, grams: item.grams ?? null };
      for (const n of NUTRIENTS) fixed[n] = item[n] ?? null;
      return fixed;
    });
  }

  // The stored owner for a message's `owner`, as websocket.py's _owner.
  _owner(owner) {
    if (owner === null) return "";
    if (!this._people.some((p) => p.key === owner)) throw NOT_FOUND;
    return owner;
  }

  _checkMeal(id, version) {
    const meal = this._meals.get(id);
    if (!meal || (version != null && meal.version !== version)) throw MEAL_CHANGED;
    return meal;
  }

  _barcodeTaken(barcode, id) {
    return barcode != null && [...this._foods.values()].some((f) => f.barcode === barcode && f.id !== id);
  }

  // Commands, as websocket.py answers them

  _listPeople() {
    return this._people.map(personJSON);
  }

  _subscribed() {
    return null;
  }

  _day(msg, person) {
    const weight = this._weights.get(person.key).get(msg.day);
    const activity = this._activity.get(person.key).get(msg.day);
    return {
      day: msg.day,
      entries: this._entryRows(person.key, (e) => e.day === msg.day),
      goals: this._goalOn(person.key, msg.day),
      weight_kg: weight ? weight.kg : null,
      activity: activity ? activityJSON(activity, msg.day === this.today) : null,
    };
  }

  _days(msg, person) {
    const span = daysFrom(msg.start, msg.end);
    if (!(span >= 0 && span < MAX_RANGE)) throw wsError("invalid_range", `end must be on or after start, within ${MAX_RANGE} days`);
    const meals = {};
    for (const e of this._entryRows(person.key, (e) => e.day >= msg.start && e.day <= msg.end)) {
      meals[e.day] ??= {};
      meals[e.day][e.meal] ??= Object.fromEntries(NUTRIENTS.map((n) => [n, 0]));
      for (const n of NUTRIENTS) meals[e.day][e.meal][n] += e[n] ?? 0;
    }
    const weights = new Map(this._weightRows(person.key, msg.start, msg.end).map((w) => [w.day, w.kg]));
    const days = [];
    for (let day = msg.start; day <= msg.end; day = addDays(day, 1)) {
      days.push({ day, meals: meals[day] ?? {}, goals: this._goalOn(person.key, day), weight_kg: weights.get(day) ?? null });
    }
    return { days };
  }

  _addEntry(msg, person) {
    const entry = { day: msg.day, meal: msg.meal };
    if ("food_id" in msg) {
      if (!("grams" in msg)) throw wsError("invalid_format", "grams is required with food_id");
      const food = this._foods.get(msg.food_id);
      if (!food) throw NOT_FOUND;
      Object.assign(entry, { food_id: food.id, name: food.name, grams: msg.grams });
      for (const n of NUTRIENTS) entry[n] = food[n] == null ? null : (food[n] * msg.grams) / 100;
    } else {
      if (!("name" in msg) || msg.kcal == null) throw wsError("invalid_format", "name and kcal are required without food_id");
      Object.assign(entry, { name: msg.name, grams: msg.grams ?? null });
      for (const n of NUTRIENTS) entry[n] = msg[n] ?? null;
    }
    const row = this._insertEntry(person.key, entry);
    this._changed(person.key, [msg.day]);
    return row;
  }

  _updateEntry(msg) {
    const old = this._entries.get(msg.entry_id);
    if (!old) throw NOT_FOUND;
    const changes = {};
    for (const key of ["day", "meal", "grams", "name", ...NUTRIENTS]) if (key in msg) changes[key] = msg[key];
    if ("grams" in changes && old.grams && !NUTRIENTS.some((n) => n in msg)) {
      const ratio = changes.grams / old.grams;
      for (const n of NUTRIENTS) changes[n] = old[n] == null ? null : old[n] * ratio;
    }
    if (changes.kcal === null) throw wsError("invalid_format", "kcal cannot be empty");
    const days = [old.day, changes.day ?? old.day];
    Object.assign(old, changes);
    this._changed(old.person, days);
    return old;
  }

  _deleteEntry(msg) {
    const old = this._entries.get(msg.entry_id);
    if (!old) throw NOT_FOUND;
    this._entries.delete(old.id);
    this._changed(old.person, [old.day]);
    return null;
  }

  _copyMeal(msg, person) {
    const copies = this._entryRows(person.key, (e) => e.day === msg.from_day && e.meal === msg.from_meal).map((e) => {
      const copy = { day: msg.to_day, meal: msg.to_meal, food_id: e.food_id, name: e.name, grams: e.grams };
      for (const n of NUTRIENTS) copy[n] = e[n];
      return copy;
    });
    const rows = copies.map((copy) => this._insertEntry(person.key, copy));
    this._changed(person.key, [msg.to_day]);
    return rows;
  }

  _searchFoods(msg) {
    const query = msg.query.trim();
    const lower = query.toLowerCase();
    const order = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
    return [...this._foods.values()]
      .filter((f) => f.name.toLowerCase().includes(lower) || f.barcode === query)
      .sort((a, b) => order(a.name.toLowerCase(), b.name.toLowerCase()) || a.id - b.id)
      .slice(0, msg.limit);
  }

  _recentFoods(msg, person) {
    const last = new Map();
    for (const e of this._entryRows(person.key, (e) => e.food_id != null)) last.set(e.food_id, Math.max(last.get(e.food_id) ?? 0, e.id));
    return [...last]
      .sort((a, b) => b[1] - a[1])
      .slice(0, msg.limit)
      .map(([id]) => this._foods.get(id));
  }

  _foodByBarcode(msg) {
    return [...this._foods.values()].find((f) => f.barcode === msg.barcode) ?? null;
  }

  _addFood(msg, person) {
    if (REQUIRED_NUTRIENTS.some((n) => msg[n] == null)) throw wsError("invalid_format", "kcal, protein, carbs and fat are required");
    const details = (f) => ({ food_id: String(f.id), name: f.name, saved_by: f.saved_by ?? "" });
    if (!msg.barcode && !msg.anyway) {
      const same = [...this._foods.values()].find((f) => f.name.toLowerCase() === msg.name.toLowerCase());
      if (same) throw detailedError("name_taken", "A saved food has this name", details(same));
    }
    if (this._barcodeTaken(msg.barcode ?? null)) {
      throw detailedError("barcode_taken", "Another food has this barcode", details(this._foodByBarcode(msg)));
    }
    const row = this._foodRow(this._nextFood++, msg, timestamp(this._now()), person?.key ?? null);
    this._foods.set(row.id, row);
    this._changed(null);
    return row;
  }

  // Like the database's UPDATE, a missing food is not found, and announced,
  // even when another food has the barcode.
  _updateFood(msg) {
    if (REQUIRED_NUTRIENTS.some((n) => n in msg && msg[n] === null)) {
      throw wsError("invalid_format", "kcal, protein, carbs and fat cannot be empty");
    }
    const food = this._foods.get(msg.food_id);
    if (food && "barcode" in msg && this._barcodeTaken(msg.barcode, food.id)) {
      throw wsError("barcode_taken", "Another food has this barcode");
    }
    const changes = Object.keys(msg).filter((k) => ["name", "barcode", ...NUTRIENTS, "portions"].includes(k));
    if (food && changes.length) {
      for (const key of changes) food[key] = key === "portions" ? msg.portions ?? [] : msg[key];
      food.updated_at = timestamp(this._now());
    }
    this._changed(null);
    if (!food) throw NOT_FOUND;
    return food;
  }

  // Entries logged from the food keep their numbers and lose the link, as
  // the database's ON DELETE SET NULL does. It leaves the meals it was in,
  // deleting those it empties. Announced even when not found.
  _deleteFood(msg) {
    const deleted = this._foods.delete(msg.food_id);
    for (const e of this._entries.values()) if (e.food_id === msg.food_id) e.food_id = null;
    if (deleted) {
      for (const meal of [...this._meals.values()]) {
        if (!meal.items.some((i) => i.food_id === msg.food_id)) continue;
        meal.items = meal.items.filter((i) => i.food_id !== msg.food_id);
        meal.version += 1;
        if (!meal.items.length) this._meals.delete(meal.id);
      }
    }
    this._changed(null);
    if (!deleted) throw NOT_FOUND;
    return null;
  }

  _foodMeals(msg) {
    return this._mealRows((m) => m.items.some((i) => i.food_id === msg.food_id)).map((m) => ({
      id: m.id,
      name: m.name,
      owner: m.owner,
      emptied: m.items.every((i) => i.food_id === msg.food_id),
    }));
  }

  _listMeals(msg, person) {
    return this._mealRows((m) => !person || m.owner === "" || m.owner === person.key);
  }

  _addMeal(msg) {
    const owner = this._owner(msg.owner);
    const clash = this._clash(owner, msg.name);
    if (clash != null) throw detailedError("meal_exists", "A saved meal has this name", { owner: clash });
    const meal = { id: this._nextMeal++, owner, name: msg.name, version: 1, items: this._mealItems(msg.items) };
    this._meals.set(meal.id, meal);
    this._changed(null);
    return this._mealJSON(meal);
  }

  _updateMeal(msg) {
    const owner = "owner" in msg ? this._owner(msg.owner) : undefined;
    const meal = this._checkMeal(msg.meal_id, msg.version);
    const changes = { name: msg.name ?? meal.name, owner: owner ?? meal.owner };
    const clash = this._clash(changes.owner, changes.name, meal.id);
    if (clash != null) throw detailedError("meal_exists", "A saved meal has this name", { owner: clash });
    const items = msg.items ? this._mealItems(msg.items) : meal.items;
    Object.assign(meal, changes, { items, version: meal.version + 1 });
    this._changed(null);
    return this._mealJSON(meal);
  }

  _deleteMeal(msg) {
    this._checkMeal(msg.meal_id, msg.version);
    this._meals.delete(msg.meal_id);
    this._changed(null);
    return null;
  }

  _logMeal(msg, person) {
    const meal = this._checkMeal(msg.meal_id, msg.version);
    if (meal.owner !== "" && meal.owner !== person.key) throw MEAL_CHANGED;
    const wanted = new Set(msg.items);
    const items = this._mealJSON(meal).items.filter((i) => wanted.has(i.id));
    if (items.length !== wanted.size) throw MEAL_CHANGED;
    const rows = items.map((i) => {
      const entry = { day: msg.day, meal: msg.meal, food_id: i.food_id, name: i.name, grams: i.grams };
      for (const n of NUTRIENTS) entry[n] = i[n];
      return this._insertEntry(person.key, entry);
    });
    this._changed(person.key, [msg.day]);
    return rows;
  }

  _searchOpenFoodFacts(msg) {
    return searchProducts(msg.query, msg.language, msg.page);
  }

  _listWeights(msg, person) {
    return this._weightRows(person.key, msg.start, msg.end ?? this.today);
  }

  _setWeight(msg, person) {
    this._weights.get(person.key).set(msg.day, { kg: msg.kg, updated_at: timestamp(this._now()) });
    this._refreshGoals(person);
    this._changed(person.key);
    return null;
  }

  _deleteWeight(msg, person) {
    this._weights.get(person.key).delete(msg.day);
    this._refreshGoals(person);
    this._changed(person.key);
    return null;
  }
}

// hass

const UNIT_SYSTEMS = {
  metric: { length: "km", accumulated_precipitation: "mm", area: "m²", mass: "kg", pressure: "Pa", temperature: "°C", volume: "L", wind_speed: "m/s" },
  us_customary: { length: "mi", accumulated_precipitation: "in", area: "ft²", mass: "lb", pressure: "psi", temperature: "°F", volume: "gal", wind_speed: "mph" },
};

const personState = (p) => ({
  entity_id: p.person_entity,
  state: "home",
  attributes: { editable: true, id: p.person_entity.slice("person.".length), device_trackers: [], user_id: p.user_id, friendly_name: p.name },
  last_changed: "2026-01-01T00:00:00+00:00",
  last_updated: "2026-01-01T00:00:00+00:00",
  context: { id: "01JZ0000000000000000000000", parent_id: null, user_id: null },
});

// Debora's watch's active calories sensor, as Garmin Connect has it, with
// what it measured today.
const ACTIVITY_SENSOR_STATE = {
  entity_id: PEOPLE[1].active_calories_entity,
  state: String(SAMPLE_ACTIVITY[0][1]),
  attributes: { state_class: "total_increasing", unit_of_measurement: "kcal", friendly_name: "Garmin Connect Active calories" },
  last_changed: "2026-01-01T00:00:00+00:00",
  last_updated: "2026-01-01T00:00:00+00:00",
  context: { id: "01JZ0000000000000000000001", parent_id: null, user_id: null },
};

// The Home Assistant app's message bus, as the frontend sees it in
// hass.auth.external, with only its barcode scanner, which reads DEMO_BARCODE.
function demoExternal() {
  let next = 1;
  return {
    config: { hasBarCodeScanner: true },
    fireMessage(message) {
      if (message.type !== "bar_code/scan") return;
      setTimeout(() => {
        this.receiveMessage({ id: next++, type: "command", command: "bar_code/scan_result", payload: { rawValue: DEMO_BARCODE, format: "ean_13" } });
      }, SCAN_MS);
    },
    // The frontend answers each command the app sends with a result.
    receiveMessage(message) {
      if (message.type === "command") this.fireMessage({ id: message.id, type: "result", success: true, result: null });
    },
  };
}

// A hass object for one card, on `store`. `locale` is the user's language;
// `unitSystem` is "metric" or "us_customary", which shows weights in lb.
function demoHass(store, { locale = "en", unitSystem = "metric" } = {}) {
  return {
    language: locale,
    locale: { language: locale, number_format: "language", time_format: "language", date_format: "language", first_weekday: "language", time_zone: "local" },
    config: { location_name: "Home", time_zone: TIME_ZONE, country: "GB", currency: "GBP", unit_system: UNIT_SYSTEMS[unitSystem], components: ["metron", "person"] },
    user: DEMO_USER,
    states: {
      ...Object.fromEntries(PEOPLE.map((p) => [p.person_entity, personState(p)])),
      [ACTIVITY_SENSOR_STATE.entity_id]: ACTIVITY_SENSOR_STATE,
    },
    auth: { external: demoExternal() },
    connection: { subscribeMessage: (callback, message) => store.subscribeMessage(callback, message) },
    callWS: (message) => store.call(message),
  };
}

// window.Metron

const CARD_TYPES = [
  "metron-food-diary-card",
  "metron-foods-card",
  "metron-meals-card",
  "metron-weight-card",
  "metron-trends-card",
  "metron-summary-card",
];

// The page's API. `clock` is the cards' clock: `fixed`, in ms, stops it, and
// `now()` reads it.
function metronDemo(clock) {
  let store = null;
  return {
    // Mounts the card `config` describes, as a dashboard's YAML would (for
    // example {type: "custom:metron-food-diary-card", person:
    // "Debora"}), at the end of `target`, and resolves to its element once
    // the card is defined. Every card shares one store of sample data,
    // seeded by the first mount. Options: `locale`, the user's language
    // (default "en"); `unitSystem`, "metric" (default) or "us_customary";
    // `today`, "YYYY-MM-DD", which only the first mount may set (default:
    // the real today in Home Assistant's time zone).
    async mount(target, config, { locale = "en", unitSystem = "metric", today } = {}) {
      const type = String(config?.type ?? "");
      const tag = type.replace(/^custom:/, "");
      if (tag === type || !CARD_TYPES.includes(tag)) throw new Error(`Metron.mount: no card of type ${type}`);
      if (!UNIT_SYSTEMS[unitSystem]) throw new Error(`Metron.mount: unitSystem must be "metric" or "us_customary", not ${unitSystem}`);
      if (today !== undefined && !isDay(today)) throw new Error(`Metron.mount: today must be a day as "YYYY-MM-DD", not ${today}`);
      if (!store) {
        // Noon UTC is the same day in Europe/London all year.
        if (today) clock.fixed = Date.parse(today) + DAY_MS / 2;
        window.fetch = demoFetch(window.fetch.bind(window));
        store = new DemoStore(clock.now);
      } else if (today && today !== store.seededOn) {
        throw new Error(`Metron.mount: the demo's today is ${store.seededOn}; reload the page to start on another day`);
      }
      const hass = demoHass(store, { locale, unitSystem });
      await customElements.whenDefined(tag);
      const card = document.createElement(tag);
      card.setConfig(config);
      card.hass = hass;
      target.append(card);
      return card;
    },
    // Puts the sample data back, and every mounted card shows it.
    reset() {
      store?.reset();
    },
  };
}
