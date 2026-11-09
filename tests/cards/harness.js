// Loads a card script for the tests. The cards are browser scripts, so each
// runs in a vm context with just enough DOM stubbed for its elements to be
// defined and configured. Interaction is covered by the end-to-end tests in
// a real browser; these cover the pure functions and the markup they build.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Loads `file`, and resolves once its cards are defined.
async function load(file) {
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
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "..", "src", file), "utf8"), ctx);
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
