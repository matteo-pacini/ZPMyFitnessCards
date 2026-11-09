// Loads a card script for the tests. The cards are browser scripts, so each
// runs in a vm context with just enough DOM stubbed for its elements to be
// defined, constructed and rendered. Rendered markup is left as a string on
// el.shadowRoot.innerHTML.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Loads `file`, and resolves once its cards are defined.
async function load(file) {
  const ctx = vm.createContext({});
  vm.runInContext(
    `
    class HTMLElement {
      attachShadow() {
        return (this.shadowRoot = { innerHTML: "" });
      }
    }
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

  // A Home Assistant connection whose zp_my_fitness/people command answers
  // `people`. Each message sent is kept on `sent`.
  hass: ({ people = [], language = "en" } = {}) => {
    const sent = [];
    return {
      sent,
      locale: { language },
      connection: {
        sendMessagePromise: async (msg) => {
          sent.push(msg);
          return people;
        },
      },
    };
  },

  // Lets pending promise callbacks run.
  settle: () => new Promise((r) => setImmediate(r)),

  // Visible text of rendered markup, without the stylesheet: tags dropped,
  // the entities esc() writes decoded, whitespace collapsed.
  text: (html) =>
    html
      .replace(/<style>[\s\S]*?<\/style>/, "")
      .replace(/<[^>]*>/g, " ")
      .replace(/&(amp|lt|gt|quot|#39);/g, (_, e) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" })[e])
      .replace(/\s+/g, " ")
      .trim(),
};
