// Builds a UX draft: one HTML page with a brief, before/after pairs with diff
// marks, animated flows played by a fake cursor, and still frames, laid out
// as AGENTS.md's "UX drafts" rule asks. A draft is a script of its own that
// builds its markup from the cards' real render functions and styles, then
// calls write():
//
//   const kit = await require("./design/drafts/kit.js").open();
//   const t = kit.strings("en", { en: { save_as_meal: "Save as meal" } });
//   kit.write("draft.html", { title, heading, intro, brief, css, cards, pairs, flows, stills });
//
// Run drafts from the repository root. design/drafts/example.js is a small
// complete one; design/drafts/check.py checks a written page in Chromium.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { load } = require("../../tests/cards/harness.js");

const KINDS = ["new", "changed", "gone"];
const DEVICES = ["phone", "app", "laptop"];

// The cards' style for `element`, with `:host` dropped and every rule put
// under `.cls`, so that a mock-up's <ha-card class="cls"> picks it up.
const scope = (css, cls) =>
  css
    .replace(/:host\s*\{[^}]*\}/g, "")
    .replace(/(^|\})\s*([^{}@]+)\{/g, (_, close, selectors) =>
      `${close}\n${selectors
        .split(",")
        .map((s) => `.${cls} ${s.trim().replace(/^ha-card/, "")}`.replace(/ \.$/, ""))
        .join(", ")} {`,
    );

const page = (draft, cardCSS) => {
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const { pairs = [], flows = [], stills = [] } = draft;
  const ids = [...pairs, ...flows, ...stills].map((x) => x.id);
  const twice = ids.find((id, i) => ids.indexOf(id) !== i);
  if (twice) throw new Error(`${twice} is used twice`);
  for (const p of pairs)
    for (const side of ["before", "after"])
      for (const [, kind] of p.marks?.[side] ?? []) if (!KINDS.includes(kind)) throw new Error(`${p.id}: no mark kind ${kind}`);
  for (const f of flows) {
    if (!DEVICES.includes(f.device)) throw new Error(`${f.id}: no device ${f.device}`);
    if (!["happy", "edge"].includes(f.group)) throw new Error(`${f.id}: group is happy or edge`);
  }
  const marks = (p, side) => esc(JSON.stringify(p.marks?.[side] ?? []));
  const pairHTML = pairs
    .map(
      (p) => `<section class="scenario" id="${p.id}"><h3><span class="id">${p.id}</span>${esc(p.title)}</h3><p>${p.text}</p>
    <div class="pair"><figure data-marks="${marks(p, "before")}"><figcaption>Before</figcaption>${p.before}</figure><figure data-marks="${marks(p, "after")}"><figcaption>After</figcaption>${p.after}</figure></div></section>`,
    )
    .join("\n");
  const flowHTML = (group) =>
    flows
      .filter((f) => f.group === group)
      .map((f) => `<section class="flow" id="${f.id}"><h3><span class="id">${f.id}</span>${esc(f.title)}</h3><div class="player" data-flow="${f.id}"></div></section>`)
      .join("\n");
  const stillHTML = stills.length
    ? `<section class="part" id="stills">
    <h2>Still frames</h2>
    <p>What has no taps to animate.</p>
    ${stills.map((s) => `<section class="scenario" id="${s.id}"><h3><span class="id">${s.id}</span>${esc(s.title)}</h3><p>${s.text}</p><div class="still">${s.html}</div></section>`).join("\n")}
  </section>`
    : "";
  const toc = [["brief", "Brief"], ["pairs", "Before and after"], ["happy", "Happy paths"], ["edge", "Edge cases"], ...(stills.length ? [["stills", "Still frames"]] : [])]
    .map(([id, label]) => `<a href="#${id}">${label}</a>`)
    .join("");
  const json = JSON.stringify(Object.fromEntries(flows.map((f) => [f.id, f])));
  // Each replacement is a function, so `$` in the markup stays as it is.
  return fs
    .readFileSync(path.join(__dirname, "page.html"), "utf8")
    .replace("<!--TITLE-->", () => esc(draft.title))
    .replace("<!--STATUS-->", () => esc(draft.status ?? "Draft for review"))
    .replace("<!--HEADING-->", () => esc(draft.heading ?? draft.title))
    .replace("<!--INTRO-->", () => draft.intro ?? "")
    .replace("<!--TOC-->", () => toc)
    .replace("<!--BRIEF-->", () => draft.brief ?? "")
    .replace("/*CARDS*/", () => cardCSS)
    .replace("/*PROPOSED*/", () => draft.css ?? "")
    .replace("<!--PAIRS-->", () => pairHTML)
    .replace("<!--HAPPY-->", () => flowHTML("happy"))
    .replace("<!--EDGE-->", () => flowHTML("edge"))
    .replace("<!--STILLS-->", () => stillHTML)
    .replace("/*FLOWS*/", () => json.replace(/<\//g, "<\\/"));
};

// Loads the cards and resolves to the kit.
async function open() {
  const ctx = await load();
  const g = (expr) => vm.runInContext(expr, ctx);
  const translate = g("translate");
  const cardStyle = (element) => {
    const card = g(`customElements.defined[${JSON.stringify(element)}]`);
    if (!card) throw new Error(`no card ${element}`);
    return card.style;
  };
  return {
    // Evaluates `expr` among the cards' scripts, for their render functions.
    g,
    esc: g("esc"),
    fill: g("fill"),
    number: g("number"),

    // The cards' strings in `lang`, then a draft's new or changed ones:
    // `extra.en` for every language, then `extra[lang]`. `lang` is kept as a
    // key, for the cards' number formatting.
    strings: (lang, extra = {}) => ({ ...translate(lang), ...extra.en, ...extra[lang], lang }),

    // A flow's step: the markup to show, its caption, and what the cursor does
    // to `target`, a selector: "tap", "type" (`extra.text`), "key"
    // (`extra.key`), or nothing, when it only points. `extra.keyboard` raises
    // the phone's keyboard, `extra.overlay` draws over the screen, and
    // `extra.narrow` narrows the card.
    step: (html, cap, target = null, act = target ? "tap" : null, extra = {}) => ({ html, cap, target, act, ...extra }),
    typeStep: (html, cap, target, text, extra = {}) => ({ html, cap, target, act: "type", text, ...extra }),
    keyStep: (html, cap, target, key, extra = {}) => ({ html, cap, target, act: "key", key, ...extra }),
    // A selector for an element marked data-t="key". Mock-ups mark the
    // elements a flow points at, as the cards' own markup has no stable IDs
    // for most of them.
    t$: (key) => `[data-t="${key}"]`,

    // Things drawn over a phone's screen, and the camera in a card.
    appScanner: (found = false) => `<div class="appscan"><div class="appbar"><span data-t="app-close">✕</span><span>Scan barcode</span></div>
      <div class="appframe${found ? " found" : ""}"><div class="bars"></div><div class="scanline"></div></div><p>Point the camera at a barcode</p><button class="appback" data-t="app-back">‹ Back</button></div>`,
    permission: (host = "home.example.com") =>
      `<div class="permission"><b>${host} wants to</b><span>Use your camera</span><div class="pbuttons"><button data-t="block">Block</button><button data-t="allow">Allow</button></div></div>`,
    viewfinder: (cancel) => `<div class="viewfinder"><div class="bars"></div><div class="scanline"></div><button class="text stop" data-t="stop-scan">${cancel}</button></div>`,

    // Writes the draft to `file`. `draft`:
    // - title, and optionally status, heading and intro (HTML);
    // - brief: HTML for the Brief section: why, what changes, what stays, and
    //   the strings it adds or changes;
    // - css: the styles the change proposes;
    // - cards: { cls: element } for each card whose styles the mock-ups use,
    //   as <ha-card class="cls">;
    // - pairs: { id, title, text (HTML), before, after, marks }, where
    //   marks.before and marks.after list [selector, kind] pairs, kind being
    //   "new", "changed" or "gone" (on Before: removed or moved away);
    // - flows: { id, title, device ("phone", "app" or "laptop"), group
    //   ("happy" or "edge"), keyboard (true when driven by keys only), steps };
    // - stills: { id, title, text (HTML), html }.
    write(file, draft) {
      const cardCSS = [g("STYLE").replace(/:host\s*\{[^}]*\}/, ""), ...Object.entries(draft.cards ?? {}).map(([cls, element]) => scope(cardStyle(element), cls))].join("\n");
      const html = page(draft, cardCSS);
      fs.writeFileSync(file, html);
      return html;
    },
  };
}

module.exports = { open, scope };
