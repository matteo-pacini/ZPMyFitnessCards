// Throws unless each of `keys` that `config` sets is text.
function assertText(config, keys) {
  for (const key of keys) {
    if (config[key] != null && typeof config[key] !== "string") throw new Error(`${key}: must be text`);
  }
}

// Base for every card: config, its editor, language, loading and live updates.
class FitnessCard extends HTMLElement {
  // Handlers for events on elements with a data-action, as "kind:action".
  static actions = {};

  // The visual editor, with a field for each of the card's static `options`,
  // labelled with the strings its static `editorStrings` swaps in.
  static getConfigElement() {
    const editor = document.createElement(EDITOR);
    editor.options = this.options;
    editor.strings = this.editorStrings;
    return editor;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    assertText(config, ["person", "title", "locale"]);
    this._config = config;
    if (this._card) this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this._config) {
      this._build();
      this._start();
    }
  }

  get _t() {
    return translate(this._locale);
  }

  get _locale() {
    return this._config.locale || this._hass?.locale?.language || "en";
  }

  get _today() {
    return todayIn(this._hass.config?.time_zone || "UTC");
  }

  connectedCallback() {
    if (this._hass && this._card && !this._unsubscribe) {
      this._subscribe();
      // A card back on the page, as when its dashboard tab shows again, heard
      // nothing while it was away: fetch what it shows again.
      if (this._loaded && !this._retry) this._refresh();
    }
    // A try at loading is due, which removing the card may have cancelled: try now.
    if (this._retry) this._start();
  }

  disconnectedCallback() {
    const unsubscribe = this._unsubscribe;
    this._unsubscribe = null;
    unsubscribe?.then((stop) => stop?.()).catch(() => {});
    // A removed card stops trying, but keeps _retry for connectedCallback.
    clearTimeout(this._retry);
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLE}${this.constructor.style}</style><ha-card></ha-card>`;
    this._card = root.querySelector("ha-card");
    root.addEventListener("click", (e) => this._onEvent(e, "click"));
    root.addEventListener("input", (e) => this._onEvent(e, "input"));
    root.addEventListener("change", (e) => this._onEvent(e, "change"));
    root.addEventListener("keydown", (e) => this._onEvent(e, "keydown"));
  }

  _onEvent(event, kind) {
    const target = event.target.closest?.("[data-action]");
    const handler = target && this.constructor.actions[`${kind}:${target.dataset.action}`];
    if (handler) handler.call(this, target, event);
  }

  _call(message) {
    return this._hass.callWS(message);
  }

  // Load what the card needs. While the integration reloads, it answers
  // not_loaded, so try again shortly. _retry is set from a failure until
  // the next try starts.
  async _start() {
    clearTimeout(this._retry);
    this._retry = null;
    try {
      await this._load();
      this._loaded = true;
      this._failure = null;
      if (!this._unsubscribe) this._subscribe();
    } catch (err) {
      this._failure = err?.code === "not_loaded" ? null : err;
      this._retry = setTimeout(() => this._start(), RETRY_MS);
    }
    this._render();
  }

  _subscribe() {
    this._unsubscribe = this._hass.connection
      .subscribeMessage((event) => this._changed(event), { type: "metron/subscribe" })
      .catch(() => {
        this._unsubscribe = null;
      });
  }
}
