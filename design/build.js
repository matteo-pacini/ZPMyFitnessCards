// Packs the cards for the Fork & Scale design system:
//
//   node design/build.js <out-dir>
//
// writes <out-dir>/components/bundle.js, one classic script that runs the
// cards, built from src/ as it is now, against design/demo-hass.js and
// defines window.ForkAndScale, and <out-dir>/components/bundle.css, the cards'
// shared styles for static previews, read from src/cards/.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { build: buildCards } = require("../scripts/build.js");
const { load } = require("../tests/cards/harness.js");

const HEADER = '/* @ds-bundle: {"format":4,"namespace":"ForkAndScale","components":[]} */';

// How Home Assistant's ha-card styles its host.
const HA_CARD_STYLE =
  "background: var(--ha-card-background, var(--card-background-color, white)); " +
  "box-shadow: var(--ha-card-box-shadow, none); box-sizing: border-box; " +
  "border-radius: var(--ha-card-border-radius, var(--ha-border-radius-lg, 12px)); " +
  "border-width: var(--ha-card-border-width, 1px); border-style: solid; " +
  "border-color: var(--ha-card-border-color, var(--divider-color, #e0e0e0)); " +
  "color: var(--primary-text-color); display: block; position: relative;";

// The frontend's elements the cards need: <home-assistant>, whose definition
// lets them register, and <ha-card>. Then the cards' clock, which reads the
// real time unless a mount stops it on another day; the cards see it as Date.
const PREAMBLE = `
if (!customElements.get("home-assistant")) customElements.define("home-assistant", class extends HTMLElement {});
if (!customElements.get("ha-card")) {
  customElements.define(
    "ha-card",
    class extends HTMLElement {
      constructor() {
        super();
        this.attachShadow({ mode: "open" }).innerHTML = ${JSON.stringify(`<style>:host { ${HA_CARD_STYLE} }</style><slot></slot>`)};
      }
    },
  );
}

const demoClock = { fixed: null, now: () => demoClock.fixed ?? Date.now() };
class DemoDate extends Date {
  constructor(...args) {
    if (args.length) super(...args);
    else super(demoClock.now());
  }

  static now() {
    return demoClock.now();
  }
}
`;

// The cards' shared styles, by the names src/cards/ gives them.
const SHARED_STYLES = "({ STYLE, 'FoodCard.style': FoodCard.style, 'PersonCard.style': PersonCard.style, CHART_STYLE, MEAL_STYLE, BAND_STYLE })";

// What a classic script, inlined in a page, must not hold.
const FORBIDDEN = [
  [/<\/script/i, "</script"],
  [/<!--/, "<!--"],
  [/\bimport\s*\(/, "import()"],
];

function bundleJS() {
  const demo = fs.readFileSync(path.join(__dirname, "demo-hass.js"), "utf8").trimEnd();
  // In a function, and strict as the cards' module is, so that nothing
  // declared here becomes a global. The cards and the demo each have a
  // function of their own, so neither sees the other's names.
  const js = `${HEADER}
(() => {
"use strict";
// Loaded already: the cards' elements cannot be defined twice.
if (window.ForkAndScale) return;
${PREAMBLE}
((Date) => {
${buildCards()}})(DemoDate);

window.ForkAndScale = (() => {
// design/demo-hass.js
${demo}

return forkAndScaleDemo(demoClock);
})();
})();
`;
  for (const [pattern, name] of FORBIDDEN) {
    if (pattern.test(js)) throw new Error(`bundle.js would contain ${name}`);
  }
  // Fails on import and export statements, which only modules may hold.
  new vm.Script(js, { filename: "bundle.js" });
  return js;
}

// `css` without its blank first and last lines and the indent its lines share.
function dedent(css) {
  const lines = css.replace(/^\s*\n/, "").trimEnd().split("\n");
  const indent = Math.min(...lines.filter((line) => line.trim()).map((line) => line.match(/^ */)[0].length));
  return lines.map((line) => line.slice(indent)).join("\n");
}

async function bundleCSS() {
  const styles = vm.runInContext(SHARED_STYLES, await load());
  return [
    '@import url("https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap");',
    "body { margin: 0; padding: 16px; font-family: Roboto, Noto, sans-serif; font-size: 14px; color: var(--primary-text-color); background: var(--primary-background-color); }",
    `ha-card { ${HA_CARD_STYLE} }`,
    ...Object.entries(styles).map(([name, css]) => `/* ${name} */\n${dedent(css)}`),
  ].join("\n\n") + "\n";
}

// bundle.js and bundle.css, as {js, css}. Throws if bundle.js would not be
// a classic script that can be inlined in a page.
async function build() {
  return { js: bundleJS(), css: await bundleCSS() };
}

// Writes the bundle into `outDir`/components/.
async function write(outDir) {
  const { js, css } = await build();
  const components = path.join(outDir, "components");
  fs.mkdirSync(components, { recursive: true });
  fs.writeFileSync(path.join(components, "bundle.js"), js);
  fs.writeFileSync(path.join(components, "bundle.css"), css);
}

if (require.main === module) {
  const outDir = process.argv[2];
  if (!outDir) {
    console.error("usage: node design/build.js <out-dir>");
    process.exit(2);
  }
  write(outDir).catch((err) => {
    console.error(err);
    process.exit(1);
  });
}

module.exports = { build, write, HEADER, SHARED_STYLES };
