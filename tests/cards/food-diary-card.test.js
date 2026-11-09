const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, hass, settle, text } = require("./harness.js");

let ctx;
let Card;
test.before(async () => {
  ctx = await load("food-diary-card.js");
  Card = ctx.customElements.defined["zp-food-diary-card"];
});

async function make(config, h) {
  const el = new Card();
  el.setConfig(config);
  el.hass = h;
  await settle();
  return el;
}

test("asks the integration for its people once", async () => {
  const h = hass({ people: [{ id: "a1", name: "Debora" }] });
  const el = await make({ person: "Debora" }, h);
  el.hass = h;
  await settle();
  // The message is built inside the vm, so a JSON round trip brings it into
  // this realm for deepEqual.
  assert.deepEqual(JSON.parse(JSON.stringify(h.sent)), [{ type: "zp_my_fitness/people" }]);
});

test("shows the person, matching the name in any case", async () => {
  const el = await make({ person: "debora" }, hass({ people: [{ id: "a1", name: "Debora" }] }));
  assert.equal(text(el.shadowRoot.innerHTML), "Food diary Debora");
});

test("says how to add a person it cannot find", async () => {
  const el = await make({ person: "Nora" }, hass({ people: [{ id: "a1", name: "Debora" }] }));
  assert.match(text(el.shadowRoot.innerHTML), /No person named Nora\. Add them in Settings/);
});

test("escapes names", async () => {
  const el = await make({ person: "<b>" }, hass({ people: [{ id: "a1", name: "<b>" }] }));
  assert.match(el.shadowRoot.innerHTML, /&lt;b&gt;/);
});

test("needs a person", () => {
  for (const config of [{}, { person: "" }, { person: "  " }, { person: 3 }]) {
    assert.throws(() => new Card().setConfig(config), /Set person:/);
  }
});

test("follows Home Assistant's language, and the locale option over it", async () => {
  const people = [{ id: "a1", name: "Debora" }];
  assert.equal(text((await make({ person: "Debora" }, hass({ people, language: "it" }))).shadowRoot.innerHTML), "Diario alimentare Debora");
  assert.equal(text((await make({ person: "Debora", locale: "sv" }, hass({ people, language: "it" }))).shadowRoot.innerHTML), "Matdagbok Debora");
});

test("Brazilian Portuguese takes Portuguese for the keys it does not override", () => {
  const { translate, STRINGS } = vm.runInContext("({ translate, STRINGS })", ctx);
  const t = translate("pt-BR");
  assert.equal(t.title, STRINGS.pt.title);
  assert.equal(t.unknown_person, STRINGS["pt-BR"].unknown_person);
  assert.equal(translate("zh-CN").title, STRINGS["zh-Hans"].title);
  assert.equal(translate("xx").title, STRINGS.en.title);
});

test("every language has every English key, with the same placeholders", () => {
  const { STRINGS } = vm.runInContext("({ STRINGS })", ctx);
  const holes = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
  for (const [lang, table] of Object.entries(STRINGS)) {
    if (lang !== "pt-BR") assert.deepEqual(Object.keys(table).sort(), Object.keys(STRINGS.en).sort(), lang);
    for (const [key, value] of Object.entries(table)) assert.deepEqual(holes(value), holes(STRINGS.en[key]), `${lang}.${key}`);
  }
  assert.equal(Object.keys(STRINGS).length, 11);
});
