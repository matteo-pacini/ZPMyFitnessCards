// The streak card: each day's state, the streak, best run and count, the
// calendar's markup, and the card's loading, failure and unknown person.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain, text } = require("./harness.js");

let ctx;
let fn;
test.before(async () => {
  ctx = await load();
  fn = vm.runInContext("({ translate, shiftDay, streakState, streakTally, streakHTML, STREAK_WINDOW, STREAK_LOOKBACK })", ctx);
});

const en = () => fn.translate("en");
const TODAY = "2026-11-13"; // a Friday
const GOAL = 1800;
const goals = (kcal) => ({ kcal, protein: 135, carbs: 180, fat: 60 });

// metron/days' days ending `today`, one per mark, the last for today:
// g on goal (1,700 kcal), o over (2,000), u nothing logged, n no goals,
// a 2,000 kcal on a day whose goal activity raised to 2,050,
// p today at 1,400 kcal, e today with nothing logged.
function history(marks, today = TODAY) {
  return [...marks].map((mark, i) => {
    const day = fn.shiftDay(today, i - marks.length + 1);
    const kcal = { g: 1700, o: 2000, a: 2000, p: 1400 }[mark];
    return {
      day,
      meals: kcal ? { lunch: { kcal: kcal - 500 }, dinner: { kcal: 500 } } : {},
      goals: mark === "n" ? null : goals(mark === "a" ? 2050 : GOAL),
      weight_kg: null,
    };
  });
}

const tally = (days, today = TODAY) => {
  const { streak, best, count } = fn.streakTally(days, today);
  return plain({ streak, best, count });
};

test("a run ending yesterday counts while today is on goal so far", () => {
  const days = history("uggggggp");
  assert.equal(fn.streakTally(days, TODAY).state(TODAY), "pending");
  assert.equal(tally(days).streak, 6);
  // Nothing logged today is on goal so far too.
  assert.equal(tally(history("uggggggge")).streak, 7);
});

test("today over goal breaks the streak at once, and the past days keep their count", () => {
  assert.deepEqual(tally(history("uggggggo")), { streak: 0, best: 6, count: { good: 6, over: 1, unlogged: 1 } });
});

test("a past day with nothing logged, or over goal, breaks the streak", () => {
  assert.equal(tally(history("ggggguggp")).streak, 2);
  assert.equal(tally(history("gggggoggp")).streak, 2);
  assert.equal(fn.streakState(history("u")[0], TODAY), "pending");
  assert.equal(fn.streakState(history("up")[0], TODAY), "unlogged");
});

test("a day without goals ends the look-back, logged or not", () => {
  assert.equal(tally(history("nggggp")).streak, 4);
  const logged = history("gggnggp");
  logged[3].meals = { dinner: { kcal: 900 } };
  assert.equal(fn.streakState(logged[3], TODAY), "before");
  assert.equal(tally(logged).streak, 2);
  // Days not in the reply are before it too.
  assert.equal(fn.streakTally(history("gp"), TODAY).state("2020-01-01"), "before");
});

test("a day is judged against its own goal, activity included", () => {
  const days = history("ggap");
  assert.equal(fn.streakState(days[2], TODAY), "good");
  assert.equal(tally(days).streak, 3);
  assert.equal(fn.streakState({ ...days[2], goals: goals(GOAL) }, TODAY), "over");
  // At the goal exactly is on goal.
  assert.equal(fn.streakState({ ...days[2], goals: goals(2000) }, TODAY), "good");
});

test("best and the count are of the last 30 days only", () => {
  assert.equal(fn.STREAK_WINDOW, 30);
  // 30 days on goal before the window, then 10 on goal, 1 over, 8 on goal,
  // 1 with nothing logged, 9 on goal and today.
  const days = history(`${"g".repeat(30)}${"g".repeat(10)}o${"g".repeat(8)}u${"g".repeat(9)}p`);
  assert.deepEqual(tally(days), { streak: 9, best: 10, count: { good: 27, over: 1, unlogged: 1 } });
});

test("a run longer than the window counts in full, as far back as the days go", () => {
  assert.deepEqual(tally(history(`u${"g".repeat(45)}p`)), { streak: 45, best: 29, count: { good: 29, over: 0, unlogged: 0 } });
  // The card fetches STREAK_LOOKBACK days, today included.
  assert.equal(fn.STREAK_LOOKBACK, 400);
  assert.equal(tally(history(`${"g".repeat(399)}p`)).streak, 399);
});

const html = (days, today = TODAY, person = "Debora") => fn.streakHTML("Streak", person, days, today, "en", en());
// The class list of the cell for `day`.
const cell = (markup, day) => markup.match(new RegExp(`<div class="([^"]*)" data-day="${day}"`))?.[1].split(" ");
const titleOf = (markup, day) => markup.match(new RegExp(`data-day="${day}" title="([^"]*)"`))?.[1];
// 30 days on goal before the window, then on goal from Oct 15 to 18, over on
// Oct 19, on goal from Oct 20 to Nov 1, nothing logged on Nov 2, on goal from
// Nov 3 to 12, and today.
const month = () => history(`${"g".repeat(30)}ggggo${"g".repeat(13)}u${"g".repeat(10)}p`);

test("runs join within a week, and not from Sunday to Monday", () => {
  const markup = html(month());
  assert.deepEqual(plain(cell(markup, "2026-11-04")), ["cell", "good", "jl", "jr"]);
  // Sunday Nov 8 and Monday Nov 9 are both on goal, in different rows.
  assert.deepEqual(plain(cell(markup, "2026-11-08")), ["cell", "good", "jl"]);
  assert.deepEqual(plain(cell(markup, "2026-11-09")), ["cell", "good", "jr"]);
  // Yesterday does not join today, which counts only at midnight.
  assert.deepEqual(plain(cell(markup, "2026-11-12")), ["cell", "good", "jl"]);
  assert.deepEqual(plain(cell(markup, "2026-11-03")), ["cell", "good", "jr"]);
  assert.deepEqual(plain(cell(markup, "2026-11-02")), ["cell", "unlogged"]);
  assert.deepEqual(plain(cell(markup, "2026-10-19")), ["cell", "over"]);
});

test("the calendar runs Monday to Sunday, from the week the window starts to the week of today", () => {
  const markup = html(month());
  const heads = [...markup.matchAll(/<div class="dow">([^<]*)<\/div>/g)].map((m) => m[1]);
  assert.deepEqual(heads, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
  const drawn = [...markup.matchAll(/data-day="([^"]*)"/g)].map((m) => m[1]);
  assert.equal(drawn[0], "2026-10-12");
  assert.equal(drawn.at(-1), "2026-11-15");
  assert.equal(drawn.length, 35);
  // Days before the window fade; days after today are kept for the grid only.
  assert.deepEqual(plain(cell(markup, "2026-10-14")), ["cell", "good", "jl", "jr", "out"]);
  assert.ok(cell(markup, "2026-10-15").every((c) => c !== "out"));
  assert.deepEqual(plain(cell(markup, "2026-11-14")), ["cell", "future"]);
  assert.equal(titleOf(markup, "2026-11-14"), undefined);
});

test("today is ringed: on goal so far, or over", () => {
  assert.deepEqual(plain(cell(html(month()), TODAY)), ["cell", "pending", "today"]);
  const over = month().map((d) => (d.day === TODAY ? { ...d, meals: { dinner: { kcal: 1960 } } } : d));
  const markup = html(over);
  assert.deepEqual(plain(cell(markup, TODAY)), ["cell", "over", "today"]);
  assert.equal(titleOf(markup, TODAY), "Fri, Nov 13: over goal, 1,960 of 1,800 kcal");
  assert.match(text(markup), /^Streak Debora 160 kcal over today 0 day streak Best 13 in 30/);
  assert.match(markup, /<div class="today-line over">/);
  assert.match(markup, /<b class="num">0<\/b>/);
});

test("each cell's title and the calendar's summary name the states in words", () => {
  const days = month().map((d) => (d.day === "2026-11-01" ? { ...d, goals: null, meals: {} } : d));
  const markup = html(days);
  assert.equal(titleOf(markup, "2026-11-09"), "Mon, Nov 9: on goal, 1,700 of 1,800 kcal");
  assert.equal(titleOf(markup, "2026-10-19"), "Mon, Oct 19: over goal, 2,000 of 1,800 kcal");
  assert.equal(titleOf(markup, "2026-11-02"), "Mon, Nov 2: nothing logged");
  assert.equal(titleOf(markup, "2026-11-01"), "Sun, Nov 1: no goal yet");
  assert.equal(titleOf(markup, TODAY), "Fri, Nov 13: today, on goal so far, 1,400 of 1,800 kcal");
  assert.deepEqual(plain(cell(markup, "2026-11-01")), ["cell", "before"]);
  const summary = markup.match(/<div class="cal num" role="img" aria-label="([^"]*)">/)[1];
  assert.equal(summary, "Debora, the last 30 days: on goal 26, over goal 1, nothing logged 1. Current streak 10, best 12.");
  // Nothing logged today: a title with no kcal.
  const empty = month().map((d) => (d.day === TODAY ? { ...d, meals: {} } : d));
  assert.equal(titleOf(html(empty), TODAY), "Fri, Nov 13: today, on goal so far");
});

test("the head gives today's line, the streak and the best; the foot the count", () => {
  const markup = html(month());
  assert.equal(
    text(markup),
    "Streak Debora 400 kcal left today 10 day streak Best 13 in 30 Mon Tue Wed Thu Fri Sat Sun " +
      "12 Oct 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 1 Nov 2 3 4 5 6 7 8 9 10 11 12 13 14 15 27 of the last 30 days",
  );
  assert.match(markup, /<b class="num live">10<\/b>/);
  assert.match(markup, /<div class="track"><i style="width:90%"><\/i><\/div>/);
  assert.match(markup, /<span class="count num">27<\/span>/);
  const empty = month().map((d) => (d.day === TODAY ? { ...d, meals: {} } : d));
  assert.match(text(html(empty)), /^Streak Debora Nothing logged today 10 day streak/);
});

test("a month tag marks the first cell and the first of each month", () => {
  const months = [...html(month()).matchAll(/data-day="([^"]*)"[^>]*><span class="d">\d+<\/span><span class="mon">([^<]*)<\/span>/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(months, [["2026-10-12", "Oct"], ["2026-11-01", "Nov"]]);
});

test("the card's words and numbers follow its language", () => {
  const markup = fn.streakHTML("Serie", "Debora", month(), TODAY, "de", fn.translate("de"));
  assert.match(text(markup), /^Serie Debora Heute noch 400 kcal übrig 10 in Folge Bestwert 13 in 30 Mo Di Mi Do Fr Sa So/);
  assert.match(text(markup), /27 der letzten 30 Tage$/);
  assert.match(markup, /title="Mo\., 9\. Nov\.: im Ziel, 1\.700 von 1\.800 kcal"/);
});

test("a new person's days before their first goals fade, and the count stays of 30", () => {
  const days = history(`${"n".repeat(25)}ggggp`);
  const markup = html(days);
  assert.deepEqual(tally(days), { streak: 4, best: 4, count: { good: 4, over: 0, unlogged: 0 } });
  assert.deepEqual(plain(cell(markup, "2026-11-01")), ["cell", "before"]);
  assert.match(text(markup), /4 of the last 30 days$/);
});

// A card on a stub of Home Assistant whose callWS answers with `reply`.
function card(config, reply) {
  const Card = ctx.customElements.defined["metron-streak-card"];
  const c = new Card();
  const sent = [];
  c._card = { innerHTML: "" };
  c._config = config;
  c._hass = {
    states: {},
    config: { time_zone: "UTC" },
    connection: { subscribeMessage: async () => () => {} },
    callWS: async (message) => {
      sent.push(plain(message));
      return reply(message);
    },
  };
  return { c, sent };
}

const PEOPLE = [{ id: "d", name: "Debora", person_entity: "person.debora" }];

test("the card fetches the look-back and draws the person's streak", async () => {
  const { c, sent } = card({ person: "debora", locale: "en" }, (m) => (m.type === "metron/people" ? PEOPLE : { days: history("uggp", c._today) }));
  await c._start();
  const today = c._today;
  assert.deepEqual(sent[1], { type: "metron/days", person: "d", start: fn.shiftDay(today, -399), end: today });
  assert.match(text(c._card.innerHTML), /^Streak Debora 400 kcal left today 2 day streak Best 2 in 30/);
  c._config = { ...c._config, title: "Mine" };
  c._render();
  assert.match(text(c._card.innerHTML), /^Mine Debora/);
});

test("the card says it is loading, what failed, and who it cannot find", async () => {
  const loading = card({ locale: "en" }, () => new Promise(() => {}));
  loading.c._render();
  assert.equal(loading.c._card.innerHTML, '<div class="title">Streak</div><div class="muted">Loading…</div>');

  const failed = card({ locale: "en" }, () => Promise.reject(new Error("Connection lost")));
  await failed.c._start();
  clearTimeout(failed.c._retry);
  assert.equal(failed.c._card.innerHTML, '<div class="title">Streak</div><div class="error">Something went wrong: Connection lost</div>');

  const unknown = card({ person: "Nora", locale: "en" }, () => PEOPLE);
  await unknown.c._start();
  assert.equal(text(unknown.c._card.innerHTML), "Streak No person named Nora. Add them in Settings, Devices & services, Metron.");
  assert.match(unknown.c._card.innerHTML, /<div class="error">/);
});

test("a person found whose days fail to load shows the title and the error, then loads on the retry", async () => {
  let fail = true;
  const { c } = card({ person: "Debora", locale: "en" }, (m) => {
    if (m.type === "metron/people") return PEOPLE;
    if (fail) return Promise.reject(new Error("boom"));
    return { days: history("uggp", c._today) };
  });
  await c._start();
  const retry = c._retry;
  clearTimeout(retry);
  assert.ok(retry);
  assert.equal(c._card.innerHTML, '<div class="title">Streak</div><div class="error">Something went wrong: boom</div>');
  fail = false;
  await c._start();
  assert.equal(c._retry, null);
  assert.match(text(c._card.innerHTML), /^Streak Debora 400 kcal left today 2 day streak/);
});

test("a failed refresh keeps the calendar drawn, and tries again", async () => {
  let fail = false;
  const { c } = card({ person: "Debora", locale: "en" }, (m) => {
    if (fail) return Promise.reject(new Error("boom"));
    return m.type === "metron/people" ? PEOPLE : { days: history("uggp", c._today) };
  });
  await c._start();
  const drawn = c._card.innerHTML;
  fail = true;
  // _refresh starts the reload without waiting for it, so wait for it here.
  const start = c._start;
  let reload;
  c._start = function () {
    reload = start.call(this);
    return reload;
  };
  try {
    await c._refresh();
    await reload;
    assert.ok(c._retry);
    assert.equal(c._failure.message, "boom");
    assert.equal(c._card.innerHTML, drawn);
  } finally {
    clearTimeout(c._retry);
  }
});

test("a failed fetch after midnight keeps yesterday's card whole, and the retry draws the new day", async () => {
  let today = TODAY;
  let fail = false;
  const { c } = card({ person: "Debora", locale: "en" }, (m) => {
    if (fail) return Promise.reject(new Error("boom"));
    return m.type === "metron/people" ? PEOPLE : { days: history("uggp", today) };
  });
  Object.defineProperty(c, "_today", { get: () => today });
  // Midnight's refresh, and the reload it falls back to, run without being
  // awaited: keep their promises to wait for them here.
  const pending = [];
  for (const name of ["_refresh", "_start"]) {
    const original = c[name];
    c[name] = function () {
      const run = original.call(this);
      pending.push(run);
      return run;
    };
  }
  try {
    await c._start();
    const drawn = c._card.innerHTML;
    assert.deepEqual(plain(cell(drawn, TODAY)), ["cell", "pending", "today"]);

    today = fn.shiftDay(TODAY, 1);
    fail = true;
    c.hass = c._hass;
    while (pending.length) await pending.shift();
    assert.equal(c._failure.message, "boom");
    assert.ok(c._retry);
    assert.equal(c._card.innerHTML, drawn);

    clearTimeout(c._retry);
    fail = false;
    await c._start();
    assert.equal(c._retry, null);
    assert.deepEqual(plain(cell(c._card.innerHTML, today)), ["cell", "pending", "today"]);
    assert.deepEqual(plain(cell(c._card.innerHTML, TODAY)), ["cell", "good", "jl"]);
  } finally {
    clearTimeout(c._retry);
  }
});

test("while the integration reloads after the person loaded, the card says it is loading", async () => {
  const { c } = card({ person: "Debora", locale: "en" }, (m) =>
    m.type === "metron/people" ? PEOPLE : Promise.reject(Object.assign(new Error("Metron is not loaded"), { code: "not_loaded" })),
  );
  await c._start();
  clearTimeout(c._retry);
  assert.equal(c._card.innerHTML, '<div class="title">Streak</div><div class="muted">Loading…</div>');
});

test("the card's editor offers person, title and language, and it has a size", () => {
  const Card = ctx.customElements.defined["metron-streak-card"];
  assert.deepEqual(plain(Card.options), ["person", "title", "locale"]);
  assert.equal(new Card().getCardSize(), 6);
});

// A card with no person in its config, which shows the one linked to who is
// logged in, so that a new name still finds them.
function linkedCard(reply) {
  const made = card({ locale: "en" }, reply);
  made.c._hass.user = { id: "u" };
  made.c._hass.states = { "person.debora": { entity_id: "person.debora", attributes: { user_id: "u" } } };
  return made;
}

const settled = () => new Promise((r) => setImmediate(r));

test("a change to the card's person reaches the open card, which draws only its body while they stay the same", async () => {
  let people = PEOPLE;
  const { c, sent } = linkedCard((m) => (m.type === "metron/people" ? people : { days: history("uggp", c._today) }));
  await c._start();
  assert.match(text(c._card.innerHTML), /^Streak Debora /);
  let whole = 0;
  const render = c._render;
  c._render = function () {
    whole += 1;
    return render.call(this);
  };

  c._changed({ person: "d" });
  await settled();
  assert.deepEqual(sent.slice(2).map((m) => m.type).sort(), ["metron/days", "metron/people"]);
  assert.equal(whole, 0);

  people = [{ ...PEOPLE[0], name: "Deborah" }];
  c._changed({ person: "d" });
  await settled();
  assert.equal(whole, 1);
  assert.match(text(c._card.innerHTML), /^Streak Deborah /);

  // Someone else's change is not this card's.
  const before = sent.length;
  c._changed({ person: "x" });
  c._changed({ person: null });
  await settled();
  assert.equal(sent.length, before);
});

test("a card whose config names a person loses them when they are renamed, and finds them again", async () => {
  let people = PEOPLE;
  const { c } = card({ person: "Debora", locale: "en" }, (m) => (m.type === "metron/people" ? people : { days: history("uggp", c._today) }));
  await c._start();
  people = [{ ...PEOPLE[0], name: "Deborah" }];
  c._changed({ person: "d" });
  await settled();
  assert.equal(text(c._card.innerHTML), "Streak No person named Debora. Add them in Settings, Devices & services, Metron.");

  // With no one to show, any person's change has the card look again.
  people = PEOPLE;
  c._changed({ person: "d" });
  await settled();
  assert.match(text(c._card.innerHTML), /^Streak Debora /);
});
