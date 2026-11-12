const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const MEALS = ["breakfast", "lunch", "dinner", "snacks"];
const MACROS = ["protein", "carbs", "fat"];
const REQUIRED_NUTRIENTS = ["kcal", ...MACROS];
const OPTIONAL_NUTRIENTS = ["fibre", "sugar", "saturated_fat", "salt"];
const NUTRIENTS = [...REQUIRED_NUTRIENTS, ...OPTIONAL_NUTRIENTS];

// How long to wait before asking a reloading integration again, in ms.
const RETRY_MS = 2000;
const SEARCH_DELAY_MS = 250;

// Sent on window when the trends card asks to open a day: {person, day}.
// A food diary showing that person moves to the day.
const OPEN_DAY = "metron-open-day";

// Dates are ISO days ("2026-11-09") in Home Assistant's time zone. new Date()
// reads one as its midnight in UTC, so format it in UTC to show that day.

function todayIn(timeZone, now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

function shiftDay(day, days) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

const number = (value, locale, digits = 0) =>
  new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);

function totals(entries) {
  const sums = Object.fromEntries(NUTRIENTS.map((n) => [n, 0]));
  for (const e of entries) for (const n of NUTRIENTS) sums[n] += e[n] ?? 0;
  return sums;
}

// The person a card shows: by name if the config gives one, else the person
// linked to the logged-in user.
function findPerson(people, config, hass) {
  if (config.person) {
    const wanted = config.person.trim().toLowerCase();
    return people.find((p) => p.name.toLowerCase() === wanted) ?? null;
  }
  const linked = Object.values(hass.states).find(
    (s) => s.entity_id.startsWith("person.") && s.attributes.user_id === hass.user?.id,
  );
  return (linked && people.find((p) => p.person_entity === linked.entity_id)) ?? null;
}

const numberValue = (input) => (input && input.value.trim() !== "" ? Number(input.value) : null);

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
  [hidden] { display: none !important; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
  .title { font-size: var(--ha-font-size-l, 1.25rem); font-weight: var(--ha-font-weight-medium, 500); }
  .sub { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); }
  button { font: inherit; cursor: pointer; border-radius: 8px; color: var(--primary-text-color); background: none; border: 0; }
  button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
  button:disabled { opacity: 0.4; cursor: default; }
  .row:hover { background: var(--secondary-background-color); }
  .text { color: var(--primary-color); padding: 6px 4px; font-weight: var(--ha-font-weight-medium, 500); }
  .fill { background: var(--primary-color); color: var(--text-primary-color); padding: 9px 14px; font-weight: var(--ha-font-weight-medium, 500); }
  .danger { background: var(--error-color); color: var(--text-primary-color); padding: 9px 14px; }
  input, select { font: inherit; color: var(--primary-text-color); background: var(--secondary-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px; padding: 8px 10px; min-width: 0; box-sizing: border-box; }
  input[type=date] { padding: 4px 6px; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: var(--ha-font-size-s, 0.875rem); color: var(--secondary-text-color); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; }
  .actions { display: flex; gap: 8px; justify-content: flex-end; align-items: center; flex-wrap: wrap; }
  .error { color: var(--error-color); }
  .muted { color: var(--secondary-text-color); }
  .num { font-variant-numeric: tabular-nums; }
`;
