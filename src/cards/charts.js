// Charts are SVG drawn in a fixed coordinate space and scaled to the card.
const CHART = { width: 600, height: 240, left: 44, right: 12, top: 12, bottom: 28 };

// A round step for about `count` axis ticks between `low` and `high`.
function niceStep(low, high, count = 4) {
  const raw = (high - low) / count || 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * power).find((step) => step >= raw);
}

function ticks(low, high, count) {
  const step = niceStep(low, high, count);
  const out = [];
  for (let v = Math.ceil(low / step) * step; v <= high + 1e-9; v += step) out.push(Math.round(v * 1000) / 1000);
  return out;
}

const daysBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);

// Places a day from `start`, at `from`, to `end`, at `to`.
function dayScale(start, end, from, to) {
  const span = Math.max(daysBetween(start, end), 1);
  return (day) => from + (daysBetween(start, day) / span) * (to - from);
}

// A line through `points`, [x, y] pairs, as an SVG path's data.
const linePath = (points) => points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");

// A chart's grid line at each of `values`, placed by `y`, with its label on
// the axis to `digits` decimals.
const gridHTML = (values, y, locale, digits = 0) =>
  values
    .map((v) => `<line class="grid" x1="${CHART.left}" x2="${CHART.width - CHART.right}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${CHART.left - 6}" y="${y(v) + 4}" text-anchor="end">${number(v, locale, digits)}</text>`)
    .join("");

const shortDate = (day, locale, withYear = false) =>
  new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", ...(withYear ? { year: "2-digit" } : {}), timeZone: "UTC" }).format(new Date(day));

const CHART_STYLE = `
  .chart { width: 100%; height: auto; display: block; overflow: visible; }
  .chart .axis, .chart .bandlabel, .chart .goallabel { font-size: 11px; fill: var(--secondary-text-color); }
  .chart .grid { stroke: var(--divider-color); stroke-width: 1; }
`;

// The meals' colours, as a fill in charts and a background elsewhere, and
// the legend that names them.
const MEAL_STYLE = `
  .meal0 { fill: var(--amber-color, var(--primary-color)); background: var(--amber-color, var(--primary-color)); }
  .meal1 { fill: var(--light-blue-color, var(--primary-color)); background: var(--light-blue-color, var(--primary-color)); }
  .meal2 { fill: var(--indigo-color, var(--primary-color)); background: var(--indigo-color, var(--primary-color)); }
  .meal3 { fill: var(--teal-color, var(--primary-color)); background: var(--teal-color, var(--primary-color)); }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: var(--ha-font-size-s, 0.875rem); color: var(--secondary-text-color); }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .legend i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
`;
