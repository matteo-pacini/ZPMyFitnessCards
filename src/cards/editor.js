// The cards' visual editor, which FitnessCard.getConfigElement opens for each
// card. It shows a field for each of the card's `options`, drawn by Home
// Assistant's own form and selectors, in the language of whoever is editing.
const EDITOR = "fork-and-scale-card-editor";

// The first choice of the person and language dropdowns, which leaves the
// option out of the config. Not "", which the frontend's dropdown shows as no
// choice at all. No person's name starts with a space, since names are
// trimmed, and no language tag does.
const DEFAULT_CHOICE = " default";

// A dropdown showing `value`, of the default choice, labelled `defaultLabel`,
// then `choices`, as [value, label] pairs. A value that is none of these is
// added as typed, so a config written by hand still shows what it says.
function dropdown(value, defaultLabel, choices) {
  const all = [[DEFAULT_CHOICE, defaultLabel], ...choices];
  if (!all.some(([v]) => v === value)) all.push([value, value]);
  return { value, selector: { select: { mode: "dropdown", options: all.map(([v, label]) => ({ value: v, label })) } } };
}

// Each option's field for a config: the value it shows, and its selector. A
// person or language the config names in another case, or with spaces around
// it, shows as the one the card finds.
const EDITOR_FIELDS = {
  person: (config, people, t) =>
    dropdown(
      config.person ? (findPerson(people, config)?.name ?? config.person) : DEFAULT_CHOICE,
      t.editor_person_linked,
      people.map((p) => [p.name, p.name]),
    ),
  title: (config) => ({ value: config.title, selector: { text: {} } }),
  locale: (config, people, t) =>
    dropdown(
      config.locale ? (knownLanguage(config.locale) ?? config.locale) : DEFAULT_CHOICE,
      t.editor_locale_default,
      Object.keys(STRINGS).map((tag) => [tag, STRINGS[tag].language_name]),
    ),
  navigation_path: (config) => ({ value: config.navigation_path, selector: { navigation: {} } }),
};

// The form for a card that takes `options`, showing `config`, with the
// integration's `people` and the strings `t`: ha-form's schema and data.
function editorForm(options, config, people, t) {
  const fields = options.map((name) => ({ name, ...EDITOR_FIELDS[name](config, people, t) }));
  return {
    schema: fields.map(({ name, selector }) => ({ name, selector })),
    data: Object.fromEntries(fields.map(({ name, value }) => [name, value])),
  };
}

// `config` with the form's `data`. A field emptied, or set to the default
// choice, is left out.
function editedConfig(config, data) {
  const edited = { ...config };
  for (const [name, value] of Object.entries(data)) {
    if (value == null || value === "" || value === DEFAULT_CHOICE) delete edited[name];
    else edited[name] = value;
  }
  return edited;
}

// Strings `t` with some keys standing for others, as a card's `editorStrings`
// gives them: {key: the key whose string it shows instead}.
const editorStrings = (t, swaps = {}) => ({ ...t, ...Object.fromEntries(Object.entries(swaps).map(([k, v]) => [k, t[v]])) });

// Home Assistant's card editor contract: it sets `hass` and calls setConfig,
// and listens for config-changed. `options` comes from getConfigElement.
class CardEditor extends HTMLElement {
  setConfig(config) {
    assertText(config, this.options);
    this._config = config;
    this._render();
  }

  set hass(hass) {
    const relabel = this._hass?.locale?.language !== hass.locale?.language;
    if (!this._hass) this._loadPeople(hass);
    this._hass = hass;
    // Every state change sets hass. Only a new language changes the form:
    // redrawing it for any other would close an open dropdown.
    if (relabel) this._render();
    else if (this._form) this._form.hass = hass;
  }

  async _loadPeople(hass) {
    this._people = await hass.callWS({ type: "fork_and_scale/people" }).catch(() => []);
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      // The frontend loads its form with the first editor that needs it. Its
      // button card's editor does, so ask for that one if nothing has yet.
      if (!customElements.get("ha-form")) customElements.get("hui-button-card")?.getConfigElement();
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (e) => this._changed(e.detail.value));
      this.append(this._form);
    }
    const t = editorStrings(translate(this._hass.locale?.language || "en"), this.strings);
    const { schema, data } = editorForm(this.options, this._config, this._people ?? [], t);
    Object.assign(this._form, {
      hass: this._hass,
      schema,
      data,
      computeLabel: (s) => t[`editor_${s.name}`],
      computeHelper: (s) => t[`editor_${s.name}_helper`],
    });
  }

  _changed(data) {
    const config = editedConfig(this._config, data);
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}
