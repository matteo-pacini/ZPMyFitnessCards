// The cards' visual editor: the form each card's options give, and the config
// a filled-in form makes.

const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { load, plain } = require("./harness.js");

let ctx;
let fn;
test.before(async () => {
  ctx = await load();
  fn = vm.runInContext("({ translate, knownLanguage, editorForm, editedConfig, DEFAULT_CHOICE, CardEditor })", ctx);
});

const en = () => fn.translate("en");
const PEOPLE = [
  { id: "a", name: "Matteo" },
  { id: "b", name: "Debora" },
];
const choices = (field) => field.selector.select.options.map((o) => [o.value, o.label]);
const form = (options, config, people = PEOPLE, t = en()) => {
  const { schema, data } = plain(fn.editorForm(options, config, people, t));
  return Object.fromEntries(schema.map((field) => [field.name, { ...field, value: data[field.name] }]));
};

test("each option has its field, in the order the card lists them", () => {
  const { schema, data } = plain(fn.editorForm(["person", "title", "locale", "navigation_path"], {}, PEOPLE, en()));
  assert.deepEqual(
    schema.map((s) => [s.name, Object.keys(s.selector)[0]]),
    [
      ["person", "select"],
      ["title", "text"],
      ["locale", "select"],
      ["navigation_path", "navigation"],
    ],
  );
  assert.deepEqual(data, { person: fn.DEFAULT_CHOICE, locale: fn.DEFAULT_CHOICE });
});

test("the person dropdown offers the logged-in user's person, then everyone", () => {
  const { person } = form(["person"], {});
  assert.equal(person.selector.select.mode, "dropdown");
  assert.deepEqual(choices(person), [
    [fn.DEFAULT_CHOICE, "The person linked to whoever is logged in"],
    ["Matteo", "Matteo"],
    ["Debora", "Debora"],
  ]);
  assert.equal(form(["person"], { person: "Debora" }).person.value, "Debora");
});

test("the language dropdown offers Home Assistant's, then each language in its own words", () => {
  const { locale } = form(["locale"], {});
  assert.deepEqual(choices(locale), [
    [fn.DEFAULT_CHOICE, "Home Assistant's language"],
    ["en", "English"],
    ["de", "Deutsch"],
    ["es", "Español"],
    ["fr", "Français"],
    ["it", "Italiano"],
    ["nl", "Nederlands"],
    ["pl", "Polski"],
    ["pt", "Português"],
    ["pt-BR", "Português (Brasil)"],
    ["sv", "Svenska"],
    ["zh-Hans", "简体中文"],
  ]);
  assert.equal(form(["locale"], { locale: "it" }).locale.value, "it");
});

test("a person and language typed by hand show as the ones the card finds", () => {
  const fields = form(["person", "locale"], { person: " debora ", locale: "pt-br" });
  assert.equal(fields.person.value, "Debora");
  assert.equal(fields.locale.value, "pt-BR");
  assert.equal(choices(fields.person).length, 3);
  assert.equal(choices(fields.locale).length, 12);
});

test("a person or language the cards do not know shows as typed", () => {
  const fields = form(["person", "locale"], { person: "Nora", locale: "en-GB" });
  assert.equal(fields.person.value, "Nora");
  assert.deepEqual(choices(fields.person).at(-1), ["Nora", "Nora"]);
  assert.equal(fields.locale.value, "en-GB");
  assert.deepEqual(choices(fields.locale).at(-1), ["en-GB", "en-GB"]);
  // Before the people load, the person typed shows on its own.
  assert.deepEqual(choices(form(["person"], { person: "Debora" }, []).person).at(-1), ["Debora", "Debora"]);
});

test("the form's choices go into the config, and the defaults and empty fields leave it", () => {
  const config = { type: "custom:metron-summary-card", person: "Matteo", title: "Mine", grid_options: { rows: 4 } };
  assert.deepEqual(plain(fn.editedConfig(config, { person: "Debora", title: "Mine", locale: "it" })), { ...config, person: "Debora", locale: "it" });
  assert.deepEqual(plain(fn.editedConfig(config, { person: fn.DEFAULT_CHOICE, title: "", locale: fn.DEFAULT_CHOICE, navigation_path: undefined })), {
    type: config.type,
    grid_options: { rows: 4 },
  });
  assert.deepEqual(plain(fn.editedConfig(config, { navigation_path: "/fs-test/0" })), { ...config, navigation_path: "/fs-test/0" });
});

test("the editor speaks the language of whoever edits", () => {
  const { person, locale } = form(["person", "locale"], {}, PEOPLE, fn.translate("de"));
  assert.equal(choices(person)[0][1], "Die Person, die mit dem angemeldeten Benutzer verknüpft ist");
  assert.equal(choices(locale)[0][1], "Sprache von Home Assistant");
  // The languages keep their own names.
  assert.deepEqual(choices(locale)[1], ["en", "English"]);
});

test("languages are found whatever their case", () => {
  assert.equal(fn.knownLanguage("PT-br"), "pt-BR");
  assert.equal(fn.knownLanguage("zh-hans"), "zh-Hans");
  assert.equal(fn.knownLanguage("en-GB"), undefined);
});

test("the editor refuses config it cannot show, as the cards do", () => {
  const editor = new fn.CardEditor();
  editor.options = ["person", "title", "locale"];
  assert.throws(() => editor.setConfig({ person: 3 }), /person: must be text/);
  assert.throws(() => editor.setConfig({ locale: ["it"] }), /locale: must be text/);
});
