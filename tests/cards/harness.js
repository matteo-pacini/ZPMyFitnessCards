// Loads the cards for the tests. The cards are browser scripts, so they run
// in a vm context with just enough DOM stubbed for their elements to be
// defined and configured. Interaction is covered by the end-to-end tests in
// a real browser; these cover the pure functions and the markup they build.

const fs = require("node:fs");
const vm = require("node:vm");
const { sources } = require("../../scripts/build.js");

// Loads the cards' scripts, and resolves once the cards are defined.
async function load() {
  const ctx = vm.createContext({ Intl, setTimeout, clearTimeout });
  vm.runInContext(
    `
    class HTMLElement {}
    var customElements = {
      defined: {},
      define(name, cls) {
        this.defined[name] = cls;
      },
      whenDefined: async () => {},
    };
    var window = globalThis;
    `,
    ctx,
  );
  // Each script runs on its own, in the bundle's order, so that coverage tools
  // attribute its code to its file. The top-level declarations of the scripts
  // in one context share a scope, as they do in the bundle's block.
  for (const source of sources) vm.runInContext(fs.readFileSync(source, "utf8"), ctx, { filename: source });
  await new Promise((r) => setImmediate(r));
  return ctx;
}

module.exports = {
  load,

  // Values built inside the vm have that realm's prototypes, which deepEqual
  // rejects; a JSON round trip brings them into this one.
  plain: (v) => JSON.parse(JSON.stringify(v)),

  // Visible text of rendered markup: tags dropped, the entities esc() writes
  // decoded, whitespace collapsed.
  text: (html) =>
    html
      .replace(/<[^>]*>/g, " ")
      .replace(/&(amp|lt|gt|quot|#39);/g, (_, e) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" })[e])
      .replace(/\s+/g, " ")
      .trim(),
};
