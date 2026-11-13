// Checks the bundle the integration serves: it matches src/, and it defines
// every card and their editor when loaded as Home Assistant loads it, as
// strict module code.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { build, out } = require("../../scripts/build.js");

test("the bundle is built from the current src/", () => {
  assert.equal(fs.readFileSync(out, "utf8"), build(), "run node scripts/build.js");
});

test("the bundle defines every card", async () => {
  const defined = [];
  const ctx = vm.createContext({
    HTMLElement: class {},
    customElements: { define: (name) => defined.push(name), whenDefined: async () => {} },
  });
  ctx.window = ctx;
  const mod = new vm.SourceTextModule(fs.readFileSync(out, "utf8"), { context: ctx });
  await mod.link(() => {});
  await mod.evaluate();
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(defined.sort(), ["metron-card-editor", "metron-food-diary-card", "metron-foods-card", "metron-meals-card", "metron-streak-card", "metron-summary-card", "metron-trends-card", "metron-weight-card"]);
  assert.deepEqual(Array.from(ctx.window.customCards, (c) => c.type).sort(), ["metron-food-diary-card", "metron-foods-card", "metron-meals-card", "metron-streak-card", "metron-summary-card", "metron-trends-card", "metron-weight-card"]);
});
