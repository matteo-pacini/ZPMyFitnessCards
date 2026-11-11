const MIN_KG = 20;
const MAX_KG = 400;

// A weight typed in `unit`, in kg. From lb that is to 0.01 kg, close enough
// to show the same 0.1 lb again.
const toKg = (value, unit) => (unit === "lb" ? Math.round(value * KG_PER_LB * 100) / 100 : value);

// The weights a person can log, in `unit`, rounded inwards to 0.1.
const weightRange = (unit) => [Math.ceil(fromKg(MIN_KG, unit) * 10) / 10, Math.floor(fromKg(MAX_KG, unit) * 10) / 10];

// Where a person's BMI bands end, in `unit`: underweight below, overweight
// from, obese from.
const bandLimits = (person, unit) => [person.underweight_below_kg, person.overweight_from_kg, person.obese_from_kg].map((kg) => fromKg(kg, unit));

// The first day a range shows, ending today. "all" starts at the first
// weigh-in, or the person's start date before there is one.
function rangeStart(range, today, firstDay) {
  if (range === "all") return firstDay && firstDay < today ? firstDay : shiftDay(today, -29);
  return shiftDay(today, -(Number(range) - 1));
}

// The weight chart in `unit`: BMI bands, the goal, and the weigh-ins from
// `start` to `today`.
function weightChartHTML(weights, person, start, today, locale, t, unit) {
  const { width, height, left, right, top, bottom } = CHART;
  const values = weights.map((w) => fromKg(w.kg, unit));
  const goalWeight = fromKg(person.goal_weight_kg, unit);
  const reference = values.length ? values : [fromKg(person.start_weight_kg, unit)];
  let low = Math.min(...reference, goalWeight) - fromKg(2, unit);
  let high = Math.max(...reference, goalWeight) + fromKg(2, unit);
  low = Math.floor(low);
  high = Math.ceil(high);
  const span = Math.max(daysBetween(start, today), 1);
  const x = (day) => left + (daysBetween(start, day) / span) * (width - left - right);
  const y = (v) => top + ((high - v) / (high - low)) * (height - top - bottom);
  const clampY = (v) => y(Math.min(Math.max(v, low), high));

  const limits = [low, ...bandLimits(person, unit), high];
  const bands = ["underweight", "healthy", "overweight", "obese"]
    .map((band, i) => {
      const from = Math.max(limits[i], low);
      const to = Math.min(limits[i + 1], high);
      if (to <= from) return "";
      const tall = clampY(from) - clampY(to);
      // Only label a band with room for its label.
      const label = tall >= 16 ? `<text class="bandlabel" x="${width - right - 4}" y="${clampY(to) + 12}" text-anchor="end">${esc(t[band])}</text>` : "";
      return `<rect class="band ${band}" x="${left}" y="${clampY(to)}" width="${width - left - right}" height="${tall}"><title>${esc(t[band])}</title></rect>${label}`;
    })
    .join("");
  const yTicks = ticks(low, high, 4)
    .map((v) => `<line class="grid" x1="${left}" x2="${width - right}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${left - 6}" y="${y(v) + 4}" text-anchor="end">${number(v, locale, 1)}</text>`)
    .join("");
  const xCount = Math.min(4, span);
  const xTicks = Array.from({ length: xCount + 1 }, (_, i) => shiftDay(start, Math.round((span * i) / xCount)))
    .map((day, i) => `<text class="axis" x="${x(day)}" y="${height - 8}" text-anchor="${i === 0 ? "start" : i === xCount ? "end" : "middle"}">${esc(shortDate(day, locale, span > 400))}</text>`)
    .join("");
  const goal = `<line class="goal" x1="${left}" x2="${width - right}" y1="${y(goalWeight)}" y2="${y(goalWeight)}"/>
    <text class="goallabel" x="${left + 4}" y="${y(goalWeight) - 4}">${esc(fill(t.goal_weight, { weight: weightText(person.goal_weight_kg, unit, locale, t) }))}</text>`;
  const path = weights.map((w, i) => `${i ? "L" : "M"}${x(w.day).toFixed(1)},${y(values[i]).toFixed(1)}`).join("");
  const points =
    weights.length <= 120
      ? weights.map((w, i) => `<circle class="point" cx="${x(w.day)}" cy="${y(values[i])}" r="3"><title>${esc(shortDate(w.day, locale, true))}: ${esc(weightText(w.kg, unit, locale, t))}</title></circle>`).join("")
      : "";
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(t.title_weight)}">
    ${bands}${yTicks}${xTicks}${goal}
    ${path ? `<path class="line" d="${path}"/>` : ""}${points}
  </svg>`;
}

class WeightCard extends PersonCard {
  static titleKey = "title_weight";
  static ranges = ["90", "365", "all"];
  static style = `${CHART_STYLE}
    .body { display: flex; flex-direction: column; gap: 14px; }
    .now { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
    .now b { font-size: 1.8rem; font-weight: var(--ha-font-weight-medium, 500); }
    .chip { border-radius: 12px; padding: 2px 10px; font-size: var(--ha-font-size-s, 0.875rem); color: var(--text-primary-color); }
    .chip.underweight, .band.underweight { background: var(--info-color, var(--blue-color)); fill: var(--info-color, var(--blue-color)); }
    .chip.healthy, .band.healthy { background: var(--success-color, var(--green-color)); fill: var(--success-color, var(--green-color)); }
    .chip.overweight, .band.overweight { background: var(--warning-color, var(--amber-color)); fill: var(--warning-color, var(--amber-color)); }
    .chip.obese, .band.obese { background: var(--error-color); fill: var(--error-color); }
    .band { fill-opacity: 0.13; }
    .chart .line { fill: none; stroke: var(--primary-color); stroke-width: 2.5; stroke-linejoin: round; }
    .chart .point { fill: var(--card-background-color, var(--primary-background-color)); stroke: var(--primary-color); stroke-width: 2; }
    .chart .goal { stroke: var(--primary-text-color); stroke-dasharray: 5 4; stroke-width: 1.2; }
    .chart .goallabel { fill: var(--primary-text-color); }
    .log { display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; align-items: end; }
    .recent { display: flex; flex-direction: column; }
    .recent .item { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; align-items: center; padding: 4px 0; border-top: 1px solid var(--divider-color); }
  `;

  getCardSize() {
    return 7;
  }

  get _range() {
    return this._chosenRange ?? "90";
  }

  async _fetch() {
    return this._call({ type: "fork_and_scale/weights", person: this._person.id });
  }

  _renderBody() {
    const body = this._card?.querySelector(".body");
    if (!body || !this._data) return;
    const t = this._t;
    const locale = this._locale;
    const person = this._person;
    const today = this._today;
    const unit = weightUnit(this._hass);
    const weights = this._data;
    const latest = weights.length ? weights[weights.length - 1].kg : person.start_weight_kg;
    const change = latest - person.start_weight_kg;
    const start = rangeStart(this._range, today, weights[0]?.day ?? person.start_date);
    const shown = weights.filter((w) => w.day >= start);
    const band = bandOf(latest, person);
    const recent = weights.slice(-5).reverse();
    const [low, high] = weightRange(unit);
    body.innerHTML = `
      <div class="now num"><b>${esc(weightText(latest, unit, locale, t))}</b>
        <span class="sub">${esc(fill(t.since_start, { change: changeText(change, unit, locale, t), date: shortDate(person.start_date, locale, true) }))}</span>
        <span class="chip ${band}">${esc(t[band])}</span></div>
      ${weightChartHTML(shown, person, start, today, locale, t, unit)}
      ${weights.length ? "" : `<div class="muted">${esc(fill(t.no_weights, { weight: weightText(person.start_weight_kg, unit, locale, t) }))}</div>`}
      <div class="log">
        <label>${esc(t.day)}<input type="date" data-field="day" value="${this._logDay ?? today}" max="${today}"></label>
        <label>${esc(t[unit])}<input type="number" data-field="weight" min="${low}" max="${high}" step="0.1" inputmode="decimal"></label>
        <button class="fill" data-action="log">${esc(t.log_weight)}</button>
      </div>
      ${this._error ? `<div class="error">${esc(this._error)}</div>` : ""}
      ${recent.length ? `<div class="recent"><div class="sub">${esc(t.recent_weights)}</div>${recent
        .map((w) => `<div class="item num"><span>${esc(shortDate(w.day, locale, true))}</span><span>${esc(weightText(w.kg, unit, locale, t))}</span>
          <button class="text" data-action="delete-weight" data-day="${w.day}" aria-label="${esc(t.delete)} ${esc(w.day)}">×</button></div>`)
        .join("")}</div>` : ""}`;
  }

  static actions = {
    "click:range"(el) {
      this._chosenRange = el.dataset.range;
      this._render();
    },
    async "click:log"() {
      const day = this._card.querySelector('[data-field="day"]').value || this._today;
      const unit = weightUnit(this._hass);
      const [low, high] = weightRange(unit);
      const weight = numberValue(this._card.querySelector('[data-field="weight"]'));
      if (weight == null || weight < low || weight > high) {
        const locale = this._locale;
        this._error = fill(this._t.error_weight, { min: number(low, locale, 1), max: number(high, locale, 1), unit: this._t[unit] });
        return this._renderBody();
      }
      this._error = null;
      this._logDay = day;
      try {
        await this._call({ type: "fork_and_scale/weight/set", person: this._person.id, day, kg: toKg(weight, unit) });
      } catch (err) {
        this._error = fill(this._t.error_failed, { message: err?.message ?? "" });
        this._renderBody();
      }
    },
    async "click:delete-weight"(el) {
      try {
        await this._call({ type: "fork_and_scale/weight/delete", person: this._person.id, day: el.dataset.day });
      } catch (err) {
        this._error = fill(this._t.error_failed, { message: err?.message ?? "" });
        this._renderBody();
      }
    },
  };
}
