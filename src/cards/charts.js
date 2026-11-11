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

const shortDate = (day, locale, withYear = false) => {
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", ...(withYear ? { year: "2-digit" } : {}), timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
};

const CHART_STYLE = `
  .chart { width: 100%; height: auto; display: block; overflow: visible; }
  .chart .axis, .chart .bandlabel, .chart .goallabel { font-size: 11px; fill: var(--secondary-text-color); }
  .chart .grid { stroke: var(--divider-color); stroke-width: 1; }
  .ranges { display: flex; gap: 4px; flex-wrap: wrap; }
  .ranges button { border: 1px solid var(--divider-color); border-radius: 16px; padding: 4px 10px; font-size: var(--ha-font-size-s, 0.875rem); }
  .ranges button[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color); border-color: var(--primary-color); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; }
  .stats b { display: block; font-size: 1.2rem; font-weight: var(--ha-font-weight-medium, 500); }
  .stats small { color: var(--secondary-text-color); font-size: var(--ha-font-size-xs, 0.75rem); }
`;
