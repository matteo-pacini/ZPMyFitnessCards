// One bar per day, or per week for long ranges, from fork_and_scale/days.
// A week's bar is the average of its logged days, and so is its goal.
function trendBars(days, weekly) {
  const logged = (d) => Object.keys(d.meals).length > 0;
  const kcal = (d) => MEALS.map((m) => d.meals[m]?.kcal ?? 0);
  if (!weekly) return days.map((d) => ({ day: d.day, days: [d.day], meals: kcal(d), goal: d.goals?.kcal ?? null }));
  const bars = [];
  // Weeks end on the last day, so the newest bar is a full week.
  for (let end = days.length; end > 0; end -= 7) {
    const week = days.slice(Math.max(0, end - 7), end);
    const counted = week.filter(logged);
    const average = (values) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0);
    const goals = counted.map((d) => d.goals?.kcal).filter((g) => g != null);
    bars.unshift({
      day: week[0].day,
      days: week.map((d) => d.day),
      meals: MEALS.map((_, i) => average(counted.map((d) => kcal(d)[i]))),
      goal: goals.length ? average(goals) : null,
    });
  }
  return bars;
}

// Averages over the logged days before `today`, which is still under way:
// kcal a day, days at or under goal, and the share of energy from each macro.
function trendStats(days, today) {
  const logged = days.filter((d) => d.day < today && Object.keys(d.meals).length > 0);
  const sum = (d, n) => MEALS.reduce((s, m) => s + (d.meals[m]?.[n] ?? 0), 0);
  const kcal = logged.reduce((s, d) => s + sum(d, "kcal"), 0);
  const energy = { protein: 4, carbs: 4, fat: 9 };
  const fromMacros = Object.fromEntries(MACROS.map((m) => [m, logged.reduce((s, d) => s + sum(d, m), 0) * energy[m]]));
  const total = MACROS.reduce((s, m) => s + fromMacros[m], 0);
  const withGoal = logged.filter((d) => d.goals);
  return {
    logged: logged.length,
    average: logged.length ? kcal / logged.length : 0,
    onGoal: withGoal.filter((d) => sum(d, "kcal") <= d.goals.kcal).length,
    withGoal: withGoal.length,
    split: Object.fromEntries(MACROS.map((m) => [m, total ? (fromMacros[m] / total) * 100 : 0])),
  };
}

function trendChartHTML(bars, weekly, locale, t) {
  const { width, height, left, right, top, bottom } = CHART;
  const totals = bars.map((b) => b.meals.reduce((a, c) => a + c, 0));
  const high = Math.max(500, ...totals, ...bars.map((b) => b.goal ?? 0)) * 1.1;
  const yTicks = ticks(0, high, 4);
  const max = yTicks[yTicks.length - 1] < high ? yTicks[yTicks.length - 1] + niceStep(0, high, 4) : yTicks[yTicks.length - 1];
  const y = (v) => top + (1 - v / max) * (height - top - bottom);
  const slot = (width - left - right) / bars.length;
  const barWidth = Math.max(2, slot * 0.64);
  const labelEvery = Math.ceil(bars.length / 7);
  const grid = gridHTML(ticks(0, max, 4), y, locale);
  const drawn = bars
    .map((bar, i) => {
      const x = left + i * slot + (slot - barWidth) / 2;
      let base = 0;
      const stack = bar.meals
        .map((v, m) => {
          if (v <= 0) return "";
          const rect = `<rect class="meal${m}" x="${x.toFixed(1)}" y="${y(base + v).toFixed(1)}" width="${barWidth.toFixed(1)}" height="${(y(base) - y(base + v)).toFixed(1)}"/>`;
          base += v;
          return rect;
        })
        .join("");
      const goal = bar.goal != null ? `<line class="goaltick" x1="${(x - 2).toFixed(1)}" x2="${(x + barWidth + 2).toFixed(1)}" y1="${y(bar.goal).toFixed(1)}" y2="${y(bar.goal).toFixed(1)}"/>` : "";
      const label = i % labelEvery === 0 || i === bars.length - 1
        ? `<text class="axis" x="${(x + barWidth / 2).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(!weekly && bars.length <= 7 ? dayLabelShort(bar.day, locale) : shortDate(bar.day, locale))}</text>`
        : "";
      const title = `${weekly ? fill(t.week_of, { date: shortDate(bar.day, locale, true) }) : shortDate(bar.day, locale, true)}: ${number(totals[i], locale)} ${t.kcal}`;
      const hit = weekly ? "" : ` data-action="open-day" data-day="${bar.day}"`;
      return `<g class="bar"${hit}><title>${esc(title)}</title>
        <rect class="hit" x="${(left + i * slot).toFixed(1)}" y="${top}" width="${slot.toFixed(1)}" height="${height - top - bottom}"/>${stack}${goal}</g>${label}`;
    })
    .join("");
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(t.title_trends)}">${grid}${drawn}</svg>`;
}

const dayLabelShort = (day, locale) => new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" }).format(new Date(day));

class TrendsCard extends PersonCard {
  static titleKey = "title_trends";
  static ranges = ["7", "30", "90", "365"];
  static style = `${super.style}${CHART_STYLE}${MEAL_STYLE}
    .body { display: flex; flex-direction: column; gap: 14px; }
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; }
    .stats b { display: block; font-size: 1.2rem; font-weight: var(--ha-font-weight-medium, 500); }
    .stats small { color: var(--secondary-text-color); font-size: var(--ha-font-size-xs, 0.75rem); }
    .chart .bar .hit { fill: transparent; }
    .chart .bar[data-action] { cursor: pointer; }
    .chart .bar[data-action]:hover .hit { fill: var(--secondary-background-color); }
    .chart .goaltick { stroke: var(--primary-text-color); stroke-width: 2; }
    .legend .goalkey { width: 14px; height: 2px; background: var(--primary-text-color); border-radius: 0; }
  `;

  getCardSize() {
    return 6;
  }

  get _range() {
    return this._chosenRange ?? "7";
  }

  async _fetch() {
    const today = this._today;
    return this._call({ type: "fork_and_scale/days", person: this._person.id, start: rangeStart(this._range, today), end: today });
  }

  _renderBody() {
    const body = this._card?.querySelector(".body");
    if (!body || !this._data) return;
    const t = this._t;
    const locale = this._locale;
    const days = this._data.days;
    const weekly = days.length > 31;
    const stats = trendStats(days, this._today);
    const split = MACROS.map((m) => `${number(stats.split[m], locale)}%`).join(" · ");
    body.innerHTML = `
      <div class="stats num">
        <div><b>${stats.logged ? number(stats.average, locale) : "–"}</b><small>${esc(t.avg_day)}</small></div>
        <div><b>${stats.withGoal ? esc(fill(t.on_goal_value, { days: stats.onGoal, logged: stats.withGoal })) : "–"}</b><small>${esc(t.on_goal)}</small></div>
        <div><b>${stats.logged ? split : "–"}</b><small>${esc(t.macro_split)}</small></div>
      </div>
      ${days.some((d) => Object.keys(d.meals).length) ? trendChartHTML(trendBars(days, weekly), weekly, locale, t) : `<div class="muted">${esc(t.no_data)}</div>`}
      <div class="legend">${MEALS.map((m, i) => `<span><i class="meal${i}"></i>${esc(t[m])}</span>`).join("")}<span><i class="goalkey"></i>${esc(t.goal)}</span></div>`;
  }

  static actions = {
    async "click:range"(el) {
      this._chosenRange = el.dataset.range;
      this._render();
      await this._refresh();
    },
    "click:open-day"(el) {
      window.dispatchEvent(new CustomEvent(OPEN_DAY, { detail: { person: this._person.id, day: el.dataset.day } }));
    },
  };
}
