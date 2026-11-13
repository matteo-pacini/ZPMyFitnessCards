// The days the streak card shows and counts, ending today.
const STREAK_WINDOW = 30;
// How far back it follows the streak: the most metron/days answers.
const STREAK_LOOKBACK = 400;

const streakKcal = (d) => MEALS.reduce((s, m) => s + (d.meals[m]?.kcal ?? 0), 0);
const streakLogged = (d) => Object.keys(d.meals).length > 0;

// The state of `d`, a metron/days day, on `today`: "good" when logged and at
// or under that day's goal, "over", "unlogged", "pending" for today until it
// goes over, or "before" for a day without goals.
function streakState(d, today) {
  if (!d.goals) return "before";
  const over = streakKcal(d) > d.goals.kcal;
  if (d.day === today) return streakLogged(d) && over ? "over" : "pending";
  if (!streakLogged(d)) return "unlogged";
  return over ? "over" : "good";
}

// From metron/days' `days`, ending `today`: `state(day)` for any day ("before"
// for one outside `days`), the current streak, the best run in the window,
// and how many days in the window were good, over and unlogged. The streak
// counts good days back from yesterday, so today joins it only at midnight,
// and is 0 once today is over.
function streakTally(days, today) {
  const states = new Map(days.map((d) => [d.day, streakState(d, today)]));
  const state = (day) => states.get(day) ?? "before";
  let streak = 0;
  if (state(today) !== "over") for (let k = shiftDay(today, -1); state(k) === "good"; k = shiftDay(k, -1)) streak++;
  let best = 0;
  let run = 0;
  const count = { good: 0, over: 0, unlogged: 0 };
  for (let k = shiftDay(today, 1 - STREAK_WINDOW); k <= today; k = shiftDay(k, 1)) {
    const s = state(k);
    run = s === "good" ? run + 1 : 0;
    best = Math.max(best, run);
    if (s in count) count[s]++;
  }
  return { state, streak, best, count };
}

// Monday is 0.
const streakWeekday = (day) => (new Date(day).getUTCDay() + 6) % 7;

// The card's markup under `title`, for `person` (a name) and `days`, the
// metron/days days from at most STREAK_LOOKBACK days back to `today`: a
// head with today's line and the streak, a Monday-first calendar of the
// window, and a foot with the count of good days.
function streakHTML(title, person, days, today, locale, t) {
  const { state, streak, best, count } = streakTally(days, today);
  const byDay = new Map(days.map((d) => [d.day, d]));
  const n = (v) => number(v, locale);
  const format = (day, options) => new Intl.DateTimeFormat(locale, { timeZone: "UTC", ...options }).format(new Date(day));
  const words = { good: t.streak_good, over: t.streak_over, unlogged: t.streak_unlogged, pending: t.streak_pending, before: t.streak_no_goal };
  const windowStart = shiftDay(today, 1 - STREAK_WINDOW);
  const start = shiftDay(windowStart, -streakWeekday(windowStart));
  const end = shiftDay(today, 6 - streakWeekday(today));
  const good = (k) => k < today && state(k) === "good";
  // 2024-01-01 was a Monday.
  const heads = [0, 1, 2, 3, 4, 5, 6].map((i) => `<div class="dow">${esc(dayLabelShort(shiftDay("2024-01-01", i), locale))}</div>`).join("");
  const cells = [];
  for (let k = start; k <= end; k = shiftDay(k, 1)) {
    const column = streakWeekday(k);
    const s = state(k);
    const cls = ["cell"];
    let title = "";
    if (k > today) cls.push("future");
    else {
      cls.push(s);
      // Runs join within a week's row, never from Sunday to Monday.
      if (good(k) && column > 0 && good(shiftDay(k, -1))) cls.push("jl");
      if (good(k) && column < 6 && good(shiftDay(k, 1))) cls.push("jr");
      if (k === today) cls.push("today");
      if (k < windowStart) cls.push("out");
      const d = byDay.get(k);
      const label = format(k, { weekday: "short", day: "numeric", month: "short" });
      title = d?.goals && streakLogged(d)
        ? fill(t.streak_cell_kcal, { day: label, state: words[s], amount: fill(t.of_goal, { food: n(streakKcal(d)), goal: n(d.goals.kcal) }) })
        : fill(t.streak_cell, { day: label, state: words[s] });
    }
    const month = k === start || k.endsWith("-01") ? `<span class="mon">${esc(format(k, { month: "short" }))}</span>` : "";
    cells.push(`<div class="${cls.join(" ")}" data-day="${k}"${title ? ` title="${esc(title)}"` : ""}><span class="d">${Number(k.slice(8))}</span>${month}</div>`);
  }
  const td = byDay.get(today);
  let todayLine = "";
  if (td?.goals) {
    const left = td.goals.kcal - streakKcal(td);
    if (!streakLogged(td)) todayLine = `<div class="today-line">${esc(t.streak_nothing_today)}</div>`;
    else if (left < 0) todayLine = `<div class="today-line over">${esc(fill(t.streak_over_today, { kcal: n(-left) }))}</div>`;
    else todayLine = `<div class="today-line">${esc(fill(t.streak_left_today, { kcal: n(left) }))}</div>`;
  }
  const summary = fill(t.streak_summary, {
    person,
    days: n(STREAK_WINDOW),
    count: n(count.good),
    over: n(count.over),
    unlogged: n(count.unlogged),
    streak: n(streak),
    best: n(best),
  });
  return `<div class="head"><div class="who"><div class="title">${esc(title)}</div><div class="sub person">${esc(person)}</div>${todayLine}</div>
      <div class="run"><div class="fig"><b class="num${streak ? " live" : ""}">${n(streak)}</b><span class="unit">${esc(t.streak_unit)}</span></div>
      <span class="best num">${esc(fill(t.streak_best, { best: n(best), days: n(STREAK_WINDOW) }))}</span></div></div>
    <div class="cal num" role="img" aria-label="${esc(summary)}">${heads}${cells.join("")}</div>
    <div class="foot"><div class="track"><i style="width:${Math.round((count.good / STREAK_WINDOW) * 100)}%"></i></div>
      <span class="count num">${n(count.good)}</span><span class="of">${esc(fill(t.streak_of_last, { days: n(STREAK_WINDOW) }))}</span></div>`;
}

class StreakCard extends PersonCard {
  static titleKey = "title_streak";
  // Not .grid, .text or .fill, which STYLE gives other meanings.
  static style = `${super.style}
    .head { align-items: flex-start; }
    .who { display: flex; flex-direction: column; min-width: 0; }
    .today-line { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); }
    .today-line.over { color: var(--error-color); }
    .run { display: flex; flex-direction: column; align-items: flex-end; text-align: right; margin-left: auto; }
    .fig { display: flex; align-items: baseline; gap: 6px; }
    .fig b { font-size: 1.8rem; line-height: 1; font-weight: var(--ha-font-weight-medium, 500); color: var(--secondary-text-color); }
    .fig b.live { color: var(--success-color, var(--green-color)); }
    .unit, .best { font-size: var(--ha-font-size-s, 0.875rem); color: var(--secondary-text-color); white-space: nowrap; }
    .cal { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); row-gap: 6px; }
    .dow { font-size: 11px; color: var(--secondary-text-color); text-align: center; padding-bottom: 2px; }
    .cell { height: 34px; margin: 0 3px; border-radius: 8px; display: flex; align-items: center; justify-content: center; gap: 2px;
      background: var(--secondary-background-color); color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); font-weight: var(--ha-font-weight-medium, 500); min-width: 0; overflow: hidden; }
    .cell .mon { font-size: var(--ha-font-size-xs, 0.75rem); }
    .cell.good { background: var(--success-color, var(--green-color)); color: var(--text-primary-color); }
    .cell.good.jl { margin-left: 0; border-top-left-radius: 0; border-bottom-left-radius: 0; }
    .cell.good.jr { margin-right: 0; border-top-right-radius: 0; border-bottom-right-radius: 0; }
    .cell.over { background: color-mix(in srgb, var(--error-color) 14%, transparent); color: var(--error-color); }
    .cell.over .d { text-decoration: line-through; text-decoration-thickness: 2px; }
    .cell.today { color: var(--primary-text-color); box-shadow: inset 0 0 0 2px var(--primary-color); }
    .cell.today.pending { background: none; }
    .cell.today.over { color: var(--error-color); }
    .cell.out, .cell.before { opacity: 0.4; }
    .cell.future { visibility: hidden; }
    .foot { display: flex; align-items: center; gap: 12px; font-size: var(--ha-font-size-s, 0.875rem); }
    .track { flex: 1 1 auto; height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
    .track i { display: block; height: 100%; background: var(--success-color, var(--green-color)); }
    .foot .of { color: var(--secondary-text-color); }
  `;

  getCardSize() {
    return 6;
  }

  async _fetch() {
    const today = this._today;
    const { days } = await this._call({ type: "metron/days", person: this._person.id, start: shiftDay(today, 1 - STREAK_LOOKBACK), end: today });
    return days;
  }

  _render() {
    if (!this._card || this._renderNoPerson()) return;
    this._renderBody();
  }

  _renderBody() {
    if (!this._card || !this._data) return;
    this._card.innerHTML = streakHTML(this._config.title || this._t.title_streak, this._person.name, this._data, this._fetchedOn, this._locale, this._t);
  }
}
