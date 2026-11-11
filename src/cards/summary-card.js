// A progress ring: `share` of the goal, drawn from the top, clockwise. Past
// the goal it fills and turns to the error colour.
function ringSVG(size, stroke, share, cls) {
  const r = (size - stroke) / 2;
  const length = 2 * Math.PI * r;
  const on = Math.min(Math.max(share, 0), 1) * length;
  const c = size / 2;
  return `<svg class="ring ${cls}${share > 1 ? " over" : ""}" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
    <circle class="track" cx="${c}" cy="${c}" r="${r}" stroke-width="${stroke}"/>
    <circle class="fill" cx="${c}" cy="${c}" r="${r}" stroke-width="${stroke}" stroke-dasharray="${on.toFixed(2)} ${length.toFixed(2)}" transform="rotate(-90 ${c} ${c})"/>
  </svg>`;
}

// A small line of weights over the last days, with the latest marked.
function sparklineSVG(weights, start, today) {
  if (weights.length < 2) return "";
  const width = 200;
  const height = 44;
  const values = weights.map((w) => w.kg);
  const low = Math.min(...values) - 0.2;
  const high = Math.max(...values) + 0.2;
  const span = Math.max(daysBetween(start, today), 1);
  const x = (day) => 3 + (daysBetween(start, day) / span) * (width - 6);
  const y = (kg) => 3 + ((high - kg) / (high - low)) * (height - 6);
  const line = weights.map((w, i) => `${i ? "L" : "M"}${x(w.day).toFixed(1)},${y(w.kg).toFixed(1)}`).join("");
  const last = weights[weights.length - 1];
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <path class="area" d="${line}L${x(last.day).toFixed(1)},${height}L${x(weights[0].day).toFixed(1)},${height}Z"/>
    <path class="line" d="${line}"/>
    <circle class="dot" cx="${x(last.day).toFixed(1)}" cy="${y(last.kg).toFixed(1)}" r="3"/>
  </svg>`;
}

// Today's summary from fork_and_scale/day, and the last 30 days of weights,
// shown in `unit`.
function summaryHTML(day, weights, person, start, today, locale, t, unit) {
  const sums = totals(day.entries);
  const goals = day.goals;
  const left = goals ? goals.kcal - sums.kcal : null;
  const centre = goals
    ? `<b class="num">${number(Math.abs(left), locale)}</b><small>${esc(left < 0 ? t.kcal_over : t.kcal_left)}</small>`
    : `<b class="num">${number(sums.kcal, locale)}</b><small>${esc(t.kcal)}</small>`;
  const minis = MACROS.map(
    (m) => `<div class="mini">${ringSVG(36, 5, goals ? sums[m] / goals[m] : 0, m)}
      <span><b>${esc(t[m])}</b><span class="sub num">${number(sums[m], locale)}${goals ? ` / ${number(goals[m], locale)}` : ""} g</span></span></div>`,
  ).join("");
  const byMeal = MEALS.map((meal) => totals(day.entries.filter((e) => e.meal === meal)).kcal);
  const scale = Math.max(goals?.kcal ?? 0, sums.kcal) || 1;
  const stack = byMeal.map((kcal, i) => (kcal > 0 ? `<i class="meal${i}" style="width:${((kcal / scale) * 100).toFixed(2)}%"></i>` : "")).join("");
  const legend = MEALS.map((meal, i) => `<span><i class="meal${i}"></i>${esc(t[meal])} <span class="num">${number(byMeal[i], locale)}</span></span>`).join("");

  const latest = weights.length ? weights[weights.length - 1].kg : person.start_weight_kg;
  const band = bandOf(latest, person);
  let change = "";
  if (weights.length >= 2) {
    change = `<small>${esc(fill(t.change_30d, { change: changeText(latest - weights[0].kg, unit, locale, t) }))}</small>`;
  }
  return `
    <div class="rings">
      <div class="big">${ringSVG(132, 12, goals ? sums.kcal / goals.kcal : 0, "kcal")}<div class="centre">${centre}</div></div>
      <div class="minis">${minis}</div>
    </div>
    ${goals ? `<div class="sub num">${esc(fill(t.of_goal, { food: number(sums.kcal, locale), goal: number(goals.kcal, locale) }))}</div>` : ""}
    <div class="stack" role="img" aria-label="${esc(t.kcal)}">${stack}</div>
    <div class="legend">${legend}</div>
    <div class="weight">
      <div><b class="num">${esc(weightText(latest, unit, locale, t))}</b> <span class="chip ${band}">${esc(t[band])}</span>${change}</div>
      ${sparklineSVG(weights, start, today)}
    </div>`;
}

class SummaryCard extends PersonCard {
  static titleKey = "title_summary";
  static ranges = [];
  static style = `${super.style}${MEAL_STYLE}${BAND_STYLE}
    .body { display: flex; flex-direction: column; gap: 12px; }
    .rings { display: grid; grid-template-columns: auto 1fr; gap: 18px; align-items: center; }
    .big { position: relative; width: 132px; height: 132px; }
    .big .centre { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
    .big b { font-size: 1.7rem; font-weight: var(--ha-font-weight-medium, 500); line-height: 1; }
    .big small, .weight small { color: var(--secondary-text-color); font-size: var(--ha-font-size-xs, 0.75rem); }
    .minis { display: flex; flex-direction: column; gap: 8px; }
    .mini { display: grid; grid-template-columns: 36px 1fr; gap: 10px; align-items: center; font-size: var(--ha-font-size-s, 0.875rem); }
    .mini b { font-weight: var(--ha-font-weight-medium, 500); display: block; }
    .ring .track { fill: none; stroke: var(--divider-color); }
    .ring .fill { fill: none; stroke-linecap: round; }
    .ring.kcal .fill { stroke: var(--primary-color); }
    .ring.protein .fill { stroke: var(--pink-color, var(--accent-color)); }
    .ring.carbs .fill { stroke: var(--amber-color, var(--warning-color)); }
    .ring.fat .fill { stroke: var(--deep-purple-color, var(--primary-color)); }
    .ring.over .fill { stroke: var(--error-color); }
    .stack { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--divider-color); }
    .stack i { display: block; height: 100%; }
    .weight { display: grid; grid-template-columns: auto 1fr; gap: 14px; align-items: center; border-top: 1px solid var(--divider-color); padding-top: 12px; }
    .weight b { font-size: 1.3rem; font-weight: var(--ha-font-weight-medium, 500); }
    .weight small { display: block; }
    .chip { border-radius: 12px; padding: 1px 8px; font-size: var(--ha-font-size-xs, 0.75rem); color: var(--text-primary-color); vertical-align: middle; }
    .spark { width: 100%; height: auto; max-height: 64px; display: block; }
    .spark .area { fill: var(--primary-color); fill-opacity: 0.12; }
    .spark .line { fill: none; stroke: var(--primary-color); stroke-width: 2; }
    .spark .dot { fill: var(--primary-color); }
    ha-card.link { cursor: pointer; }
  `;

  static options = ["person", "title", "locale", "navigation_path"];

  getCardSize() {
    return 5;
  }

  setConfig(config) {
    if (config?.navigation_path != null && typeof config.navigation_path !== "string") {
      throw new Error("navigation_path: must be text");
    }
    super.setConfig(config);
  }

  set hass(hass) {
    super.hass = hass;
    // Show the new day once midnight passes.
    if (this._data && this._data.day.day !== this._today) this._refresh();
  }

  get hass() {
    return this._hass;
  }

  async _fetch() {
    const today = this._today;
    const start = shiftDay(today, -29);
    const [day, weights] = await Promise.all([
      this._call({ type: "fork_and_scale/day", person: this._person.id, day: today }),
      this._call({ type: "fork_and_scale/weights", person: this._person.id, start }),
    ]);
    return { day, weights, start };
  }

  _render() {
    super._render();
    this._card?.classList?.toggle?.("link", Boolean(this._config.navigation_path));
  }

  _renderBody() {
    const body = this._card?.querySelector(".body");
    if (!body || !this._data) return;
    const { day, weights, start } = this._data;
    body.innerHTML = summaryHTML(day, weights, this._person, start, this._today, this._locale, this._t, weightUnit(this._hass));
  }

  static actions = {};

  _build() {
    super._build();
    this._card.addEventListener("click", () => {
      const path = this._config.navigation_path;
      if (!path) return;
      history.pushState(null, "", path);
      window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
    });
  }
}
