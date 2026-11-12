// Active calories in the cards: the food diary's Goal + Activity − Food =
// Remaining and the line under it, and the summary card's line, from
// metron/day's `activity`. Each test names the spec's "Paths to test" rows it
// covers, by flow ID (H1…E14) or rule. The cards' interaction and live
// updates are tested end to end.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, text } = require("./harness.js");

let ctx;
let fn;
test.before(async () => {
  ctx = await load();
  fn = vm.runInContext("({ translate, percent, activityLine, diaryBodyHTML, diarySummaryHTML, summaryFoodHTML, FoodDiaryCard })", ctx);
});

const GARMIN = "sensor.garmin_connect_active_calories";
const IPHONE = "sensor.ben_s_iphone_active_energy";
const STATES = {
  [GARMIN]: { entity_id: GARMIN, state: "906", attributes: { unit_of_measurement: "kcal", friendly_name: "Garmin Connect Active calories" } },
  [IPHONE]: { entity_id: IPHONE, state: "240", attributes: { unit_of_measurement: "kcal", friendly_name: "Ben's iPhone Active Energy" } },
};

// The spec's people. Anna: resting burn 1,395.25 kcal and Light, so her
// level allows for 244 kcal and her goal without activity is 1,368. Ben:
// Sedentary, which allows for none. Debora: Moderate, 493 allowed for.
const ANNA = 1395.25 * (1.375 - 1.2);
const ANNA_BASE = 1395.25 * 1.375 - 550;
const BEN = 0;
const DEBORA = 1409.25 * (1.55 - 1.2);

// metron/day's activity for `measured` kcal, of which `counted` count, as
// goals.py works it out, on a day with `status` (null on a past day).
const activity = (measured, counted, status, { source = GARMIN, allowed = ANNA } = {}) => ({
  source,
  measured,
  counted,
  added: Math.max(0, counted - allowed),
  allowed,
  share: 75,
  cap: 1500,
  status,
});

const line = (a, locale = "en", states = STATES) => fn.activityLine(a, states, "Anna", locale, fn.translate(locale));

// A day's goals for a goal of `kcal`, as data.py records them.
const goals = (kcal) => ({ kcal, protein: (kcal * 0.3) / 4, carbs: (kcal * 0.4) / 4, fat: (kcal * 0.3) / 9 });

// Anna's evening as the draft has it: 850 kcal eaten.
const EVENING = [
  { id: 1, meal: "breakfast", name: "Porridge oats", grams: 60, kcal: 227, protein: 7.9, carbs: 36, fat: 4.2 },
  { id: 2, meal: "breakfast", name: "Semi-skimmed milk", grams: 200, kcal: 98, protein: 7.2, carbs: 9.6, fat: 3.4 },
  { id: 3, meal: "lunch", name: "Chicken salad wrap", grams: 220, kcal: 420, protein: 28, carbs: 38, fat: 16 },
  { id: 4, meal: "snacks", name: "Banana", grams: 118, kcal: 105, protein: 1.3, carbs: 27, fat: 0.4 },
];

// The day metron/day gives for Anna with `a`, whose goal is her base plus what it added.
const annaDay = (a, entries = EVENING) => ({
  day: "2026-11-12",
  entries,
  goals: goals(Math.round(ANNA_BASE + (a?.added ?? 0))),
  weight_kg: null,
  activity: a,
});

test("the line for each status of a sensor (H2, E3, E4, E9, E11)", () => {
  // H2: within the level, then beyond it.
  assert.equal(
    line(activity(120, 90, "level")),
    "Garmin Connect Active calories measured 120 kcal. At 75%, that counts as 90 kcal. The activity level already allows for 244 kcal, so none of it is added.",
  );
  assert.equal(
    line(activity(906, 680, "counting")),
    "Garmin Connect Active calories measured 906 kcal. At 75%, that counts as 680 kcal. The activity level already allows for 244 kcal of it.",
  );
  // E4: over the cap the line shows the figure measured, and the cap that counts.
  assert.equal(
    line(activity(2950, 1500, "capped")),
    "Garmin Connect Active calories measured 2,950 kcal. At 75%, that is over the daily limit, so 1,500 kcal counts. The activity level already allows for 244 kcal of it.",
  );
  // E3: unavailable, holding today's last reading.
  assert.equal(
    line(activity(500, 380, "unavailable")),
    "Garmin Connect Active calories is unavailable, so this uses its last reading from today, 500 kcal. At 75%, that counts as 380 kcal. The activity level already allows for 244 kcal of it.",
  );
  // E11: unavailable or unknown with nothing held reads as waiting, as does a stale reading (E1).
  assert.equal(line(activity(null, 0, "waiting")), "Garmin Connect Active calories has no reading for today yet.");
  // E9: a missing sensor is named by its entity ID, even if a name is still to hand, and its held reading still counts.
  assert.equal(
    line(activity(500, 380, "missing")),
    `Home Assistant no longer has ${GARMIN}. Choose another sensor for Anna in Settings, Devices & services, Metron. Until then, this uses its last reading from today, 500 kcal. At 75%, that counts as 380 kcal. The activity level already allows for 244 kcal of it.`,
  );
  // E9, the next day: nothing held, so the line only says what to do.
  assert.equal(line(activity(null, 0, "missing")), `Home Assistant no longer has ${GARMIN}. Choose another sensor for Anna in Settings, Devices & services, Metron.`);
});

test("the line for each status of the action, which says logged (H5)", () => {
  const logged = (measured, counted, status) => line(activity(measured, counted, status, { source: "action", allowed: DEBORA }));
  // Before the first call today.
  assert.equal(logged(null, 0, "waiting"), "No active calories logged for today yet.");
  assert.equal(logged(380, 280, "level"), "Active calories logged: 380 kcal. At 75%, that counts as 280 kcal. The activity level already allows for 493 kcal, so none of it is added.");
  assert.equal(logged(900, 680, "counting"), "Active calories logged: 900 kcal. At 75%, that counts as 680 kcal. The activity level already allows for 493 kcal of it.");
  assert.equal(
    logged(2950, 1500, "capped"),
    "Active calories logged: 2,950 kcal. At 75%, that is over the daily limit, so 1,500 kcal counts. The activity level already allows for 493 kcal of it.",
  );
  // A past day, from the action (H6).
  assert.equal(logged(1150, 860, null), "Active calories logged: 1,150 kcal. At 75%, that counts as 860 kcal. The activity level already allows for 493 kcal of it.");
});

test("Sedentary allows for none of what counts, so all of it is added (H3)", () => {
  const ben = activity(240, 180, "counting", { source: IPHONE, allowed: BEN });
  assert.equal(line(ben), "Ben's iPhone Active Energy measured 240 kcal. At 75%, that counts as 180 kcal. The activity level allows for none of it.");
  assert.equal(line({ ...ben, measured: 30, counted: 20, added: 20 }), "Ben's iPhone Active Energy measured 30 kcal. At 75%, that counts as 20 kcal. The activity level allows for none of it.");
  const sum = text(fn.diarySummaryHTML({ kcal: 1000, protein: 0, carbs: 0, fat: 0 }, goals(1904), fn.translate("en"), "en-GB", ben, line(ben)));
  assert.match(sum, /^1,724 Goal \+ 180 Activity − 1,000 Food = 904 Remaining Ben's iPhone/);
});

test("a past day's line explains it by its own figures, with no status (H4)", () => {
  assert.equal(
    line(activity(1240, 930, null)),
    "Garmin Connect Active calories measured 1,240 kcal. At 75%, that counts as 930 kcal. The activity level already allows for 244 kcal of it.",
  );
  // The cap applied that day: the figures say so, since past days have no status.
  assert.match(line(activity(2950, 1500, null)), /At 75%, that is over the daily limit, so 1,500 kcal counts\./);
  // At exactly the cap, it counts in full.
  assert.match(line(activity(2000, 1500, null)), /At 75%, that counts as 1,500 kcal\./);
  // Within the level that day.
  assert.match(line(activity(300, 220, null)), /already allows for 244 kcal, so none of it is added\.$/);
  // A sensor Home Assistant no longer has, or never named, is named by its entity ID.
  assert.match(line(activity(1240, 930, null), "en", {}), new RegExp(`^${GARMIN} measured 1,240 kcal\\.`));
  const unnamed = { [GARMIN]: { entity_id: GARMIN, state: "1", attributes: {} } };
  assert.match(line(activity(1240, 930, null), "en", unnamed), new RegExp(`^${GARMIN} measured`));
});

test("the line in German, with four-digit figures, for each status (E8)", () => {
  assert.equal(
    line(activity(906, 680, "counting"), "de"),
    "Garmin Connect Active calories hat 906 kcal gemessen. Davon zählen 75\u00a0%: 680 kcal. Das Aktivitätsniveau berücksichtigt davon bereits 244 kcal.",
  );
  assert.equal(
    line(activity(500, 380, "unavailable"), "de"),
    "Garmin Connect Active calories ist nicht verfügbar. Verwendet wird der letzte Wert von heute: 500 kcal. Davon zählen 75\u00a0%: 380 kcal. Das Aktivitätsniveau berücksichtigt davon bereits 244 kcal.",
  );
  assert.equal(
    line(activity(2950, 1500, "capped"), "de"),
    "Garmin Connect Active calories hat 2.950 kcal gemessen. 75\u00a0% davon liegen über dem Tageslimit, daher zählen 1.500 kcal. Das Aktivitätsniveau berücksichtigt davon bereits 244 kcal.",
  );
  assert.equal(line(activity(120, 90, "level"), "de"), "Garmin Connect Active calories hat 120 kcal gemessen. Davon zählen 75\u00a0%: 90 kcal. Das Aktivitätsniveau berücksichtigt bereits 244 kcal, daher kommt nichts hinzu.");
  assert.equal(line(activity(null, 0, "waiting"), "de"), "Garmin Connect Active calories hat für heute noch keinen Wert.");
  assert.equal(
    line(activity(null, 0, "missing"), "de"),
    `Home Assistant hat ${GARMIN} nicht mehr. Wähle unter Einstellungen, Geräte & Dienste, Metron einen anderen Sensor für Anna.`,
  );
  assert.equal(
    line(activity(500, 380, "missing"), "de"),
    `Home Assistant hat ${GARMIN} nicht mehr. Wähle unter Einstellungen, Geräte & Dienste, Metron einen anderen Sensor für Anna. Bis dahin wird der letzte Wert von heute verwendet: 500 kcal. Davon zählen 75\u00a0%: 380 kcal. Das Aktivitätsniveau berücksichtigt davon bereits 244 kcal.`,
  );
  assert.equal(line(activity(null, 0, "waiting", { source: "action" }), "de"), "Für heute sind noch keine aktiven Kalorien erfasst.");
  assert.match(line(activity(900, 680, "counting", { source: "action" }), "de"), /^Erfasste aktive Kalorien: 900 kcal\. /);

  // The marathon: four-digit Goal, Activity and Food.
  const marathon = [{ id: 1, meal: "lunch", name: "Pasta", grams: null, kcal: 1875, protein: 0, carbs: 0, fat: 0 }];
  const body = text(fn.diaryBodyHTML(annaDay(activity(2950, 1500, "capped"), marathon), fn.translate("de"), "de", STATES, "Anna"));
  assert.match(body, /^1\.368 Ziel \+ 1\.256 Aktivität − 1\.875 Essen = 749 Übrig Garmin Connect/);
});

test("on a narrow card the seven-column sum's figures go a size down, so that it fits (E8)", () => {
  // Whether it fits is measured in a browser, end to end; this holds the rule in place.
  const style = fn.FoodDiaryCard.style;
  assert.match(style, /\.summary\.withactivity \{ grid-template-columns: 1fr auto 1fr auto 1fr auto 1fr; container-type: inline-size; \}/);
  assert.match(style, /@container \(max-width: 320px\) \{\s*\.summary\.withactivity b, \.summary\.withactivity \.op \{ font-size: 1\.05rem; \}\s*\}/);
  // The five-column sum keeps its size.
  assert.match(style, /\.summary b \{ display: block; font-size: 1\.3rem;/);
});

test("Chinese runs the line's sentences together, the other languages space them", () => {
  const counting = activity(906, 680, "counting");
  assert.equal(line(counting, "zh-Hans"), "Garmin Connect Active calories 测得 906 千卡。按 75% 计，算作 680 千卡。活动水平已包含其中的 244 千卡。");
  // Any Chinese reads the zh-Hans strings, so joins them the same way.
  assert.equal(line(counting, "zh-CN"), line(counting, "zh-Hans"));
  assert.equal(line(counting, "ZH-hans"), line(counting, "zh-Hans"));
  for (const locale of ["en", "de", "es", "fr", "it", "nl", "pl", "pt", "pt-BR", "sv"]) {
    assert.equal(line(counting, locale).split(". ").length, 3, locale);
  }
});

test("percentages are written as each language writes them", () => {
  const expected = {
    en: "75%",
    de: "75\u00a0%",
    es: "75\u00a0%",
    fr: "75\u00a0%",
    it: "75%",
    nl: "75%",
    pl: "75%",
    pt: "75%",
    "pt-BR": "75%",
    sv: "75\u00a0%",
    "zh-Hans": "75%",
  };
  for (const [locale, share] of Object.entries(expected)) {
    assert.equal(fn.percent(75, locale), share, locale);
    assert.ok(line(activity(906, 680, "counting"), locale).includes(share), locale);
  }
  assert.equal(fn.percent(100, "en"), "100%");
  assert.equal(fn.percent(5, "de"), "5\u00a0%");
});

test("a day with activity sums Goal + Activity − Food = Remaining, in seven columns; one without keeps five (H1, H2, H4)", () => {
  const t = fn.translate("en");
  const sums = { kcal: 850, protein: 44.4, carbs: 110.6, fat: 24 };
  // H1: within the level, the seven columns still show, with Activity 0.
  const level = activity(80, 60, "level");
  const zero = fn.diarySummaryHTML(sums, goals(1368), t, "en-GB", level, line(level));
  assert.match(zero, /<div class="summary num withactivity">/);
  assert.match(text(zero), /^1,368 Goal \+ 0 Activity − 850 Food = 518 Remaining Garmin Connect Active calories measured 80 kcal\./);
  // H2: Activity 136, then 436, against the same goal without activity.
  for (const [a, total, shown] of [
    [activity(500, 380, "counting"), 1504, "1,368 Goal + 136 Activity − 850 Food = 654 Remaining"],
    [activity(906, 680, "counting"), 1804, "1,368 Goal + 436 Activity − 850 Food = 954 Remaining"],
  ]) {
    const html = fn.diarySummaryHTML(sums, goals(total), t, "en-GB", a, line(a));
    assert.ok(text(html).startsWith(shown), shown);
    assert.equal(html.match(/<span class="op">/g).length, 3);
    // The line sits between the sum and the macros, which measure against the total.
    assert.match(html, /<\/div><div class="activity">Garmin[^<]*<\/div>\s*<div class="macros num">/);
    assert.match(text(html), new RegExp(`Protein 44 / ${Math.round((total * 0.3) / 4)} g`));
  }
  // H4: a day without activity: five columns and no line.
  const plain = fn.diarySummaryHTML(sums, goals(1368), t, "en-GB");
  assert.doesNotMatch(plain, /withactivity|class="activity"/);
  assert.equal(plain.match(/<span class="op">/g).length, 2);
  assert.match(text(plain), /^1,368 Goal − 850 Food = 518 Remaining Protein/);
  // Over the goal, as before.
  const over = activity(906, 680, "counting");
  assert.match(text(fn.diarySummaryHTML({ ...sums, kcal: 2000 }, goals(1804), t, "en-GB", over, line(over))), /^1,368 Goal \+ 436 Activity − 2,000 Food = 196 Over/);
});

test("the sum adds up as shown, however added is rounded", () => {
  const a = { ...activity(906, 680, "counting"), added: 435.5 };
  // 1,804 − 435.5 = 1,368.5 would show as 1,369, and 1,369 + 436 is not 1,804.
  const shown = text(fn.diarySummaryHTML({ kcal: 850, protein: 0, carbs: 0, fat: 0 }, goals(1804), fn.translate("en"), "en-GB", a, ""));
  assert.match(shown, /^1,368 Goal \+ 436 Activity − 850 Food = 954 Remaining/);
});

test("the diary's body draws the day's activity, its line naming the sensor and the person (H2, H4, E9)", () => {
  const t = fn.translate("en");
  const today = text(fn.diaryBodyHTML(annaDay(activity(906, 680, "counting")), t, "en-GB", STATES, "Anna"));
  assert.match(today, /^1,368 Goal \+ 436 Activity − 850 Food = 954 Remaining Garmin Connect Active calories measured 906 kcal\. .* Breakfast 325 kcal/);
  const gone = text(fn.diaryBodyHTML(annaDay(activity(null, 0, "missing"), []), t, "en-GB", STATES, "Anna"));
  assert.match(gone, /^1,368 Goal \+ 0 Activity − 0 Food = 1,368 Remaining Home Assistant no longer has .* for Anna in Settings/);
  // H4: a day before active calories were allowed.
  const before = fn.diaryBodyHTML(annaDay(null), t, "en-GB", STATES, "Anna");
  assert.doesNotMatch(before, /withactivity|class="activity"/);
  assert.match(text(before), /^1,368 Goal − 850 Food = 518 Remaining Protein/);
  // A reply from before metron/day had activity at all.
  const { activity: _, ...older } = annaDay(null);
  assert.match(text(fn.diaryBodyHTML(older, t, "en-GB")), /^1,368 Goal − 850 Food/);
});

test("the food diary card draws its day with Home Assistant's names for the sensor and the person (H2)", () => {
  const Card = ctx.customElements.defined["metron-food-diary-card"];
  const card = new Card();
  const body = { innerHTML: "" };
  card._config = { locale: "en-GB" };
  card._hass = { states: STATES };
  card._card = { querySelector: (selector) => (selector === ".body" ? body : null) };
  card._person = { id: "anna", name: "Anna" };
  card._data = annaDay(activity(500, 380, "missing"));
  card._renderBody();
  assert.match(text(body.innerHTML), new RegExp(`^1,368 Goal \\+ 136 Activity − 850 Food = 654 Remaining Home Assistant no longer has ${GARMIN}\\. Choose another sensor for Anna`));
});

test("the summary card's line measures against the total, and names the activity (B4, H2)", () => {
  const t = fn.translate("en");
  const day = annaDay(activity(906, 680, "counting"));
  const html = fn.summaryFoodHTML(day, "en-GB", t);
  // The ring and kcal left measure against the total.
  assert.match(text(html), /^954 kcal left .* 850 of 1,804 kcal, 436 from activity Breakfast/);
  assert.match(html, new RegExp(`stroke-dasharray="${((850 / 1804) * 2 * Math.PI * 60).toFixed(2)} `));
  // Within the level, the activity reads 0.
  assert.match(text(fn.summaryFoodHTML(annaDay(activity(120, 90, "level")), "en-GB", t)), /850 of 1,368 kcal, 0 from activity/);
  assert.match(text(fn.summaryFoodHTML(day, "de", fn.translate("de"))), /850 von 1\.804 kcal, 436 durch Aktivität/);
  // Without activity the line is as it was.
  assert.match(text(fn.summaryFoodHTML(annaDay(null), "en-GB", t)), /^518 kcal left .* 850 of 1,368 kcal Breakfast/);
  const { activity: _, ...older } = annaDay(null);
  assert.match(text(fn.summaryFoodHTML(older, "en-GB", t)), / 850 of 1,368 kcal Breakfast/);
  // With no goals yet there is no line.
  assert.doesNotMatch(text(fn.summaryFoodHTML({ ...older, goals: null }, "en-GB", t)), / of /);
});
