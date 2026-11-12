// The UX draft kit, design/drafts/: it still builds a draft from the cards as
// they are, and refuses a malformed one. design/drafts/check.py checks a page
// in a browser; this checks what can be checked without one.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const kit = require("../../design/drafts/kit.js");
const example = require("../../design/drafts/example.js");

let dir;
test.before(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "drafts-"));
});
test.after(() => fs.rmSync(dir, { recursive: true, force: true }));

// Whether some tag in `html` has every attribute of `selector`, a run of
// [name="value"] parts, the only selectors this test reads.
const hasTarget = (html, selector) => {
  const parts = [...selector.matchAll(/\[([\w-]+)="([^"]*)"\]/g)].map((m) => `${m[1]}="${m[2]}"`);
  assert.ok(parts.length, `can't read ${selector}`);
  return [...html.matchAll(/<[^>]+>/g)].some(([tag]) => parts.every((p) => tag.includes(p)));
};

test("the example draft builds, with every step's target in its markup", async () => {
  const file = path.join(dir, "example.html");
  const html = await example.build(file);
  assert.equal(fs.readFileSync(file, "utf8"), html);
  assert.doesNotMatch(html, /<!--[A-Z]+-->|\/\*[A-Z]+\*\//, "every placeholder filled");
  assert.match(html, /<title>Example Draft<\/title>/);
  assert.match(html, /<figure data-marks="\[\[&quot;\[data-t=\\&quot;clear\\&quot;\]&quot;,&quot;new&quot;\]\]">/);
  assert.match(html, /\.diary \.bar \{/, "the diary card's styles, scoped");
  const flows = JSON.parse(html.match(/<script type="application\/json" id="flows">(.*?)<\/script>/s)[1]);
  assert.deepEqual(Object.keys(flows), ["H1", "E1"]);
  for (const f of Object.values(flows))
    f.steps.forEach((s, i) => {
      if (s.target) assert.ok(hasTarget(s.html, s.target), `${f.id} step ${i + 1}: no ${s.target}`);
    });
  assert.ok(!html.includes('id="stills"'), "no still frames, so no section for them");
});

test("a draft is refused with a repeated ID, an unknown mark, device or group", async () => {
  const k = await kit.open();
  const file = path.join(dir, "bad.html");
  const pair = { id: "B1", title: "", text: "", before: "", after: "" };
  const flow = { id: "H1", title: "", device: "phone", group: "happy", steps: [] };
  assert.throws(() => k.write(file, { title: "x", pairs: [pair], flows: [{ ...flow, id: "B1" }] }), /B1 is used twice/);
  assert.throws(() => k.write(file, { title: "x", pairs: [{ ...pair, marks: { after: [["b", "added"]] } }] }), /no mark kind added/);
  assert.throws(() => k.write(file, { title: "x", flows: [{ ...flow, device: "tablet" }] }), /no device tablet/);
  assert.throws(() => k.write(file, { title: "x", flows: [{ ...flow, group: "sad" }] }), /happy or edge/);
  assert.ok(!fs.existsSync(file));
});

test("markup with $ patterns reaches the page as it is", async () => {
  const k = await kit.open();
  const html = k.write(path.join(dir, "dollars.html"), { title: "x", brief: "<p>$& $1 $$</p>" });
  assert.ok(html.includes("<p>$& $1 $$</p>"));
});

test("scope puts a card's rules under its class and drops :host", () => {
  const css = kit.scope(":host { display: block; } ha-card { padding: 0; } .a, .b > i { color: red; }", "x");
  assert.equal(css.trim(), ".x  { padding: 0; }\n.x .a, .x .b > i { color: red; }");
});
