// Throws unless each of `keys` that `config` sets is text.
function assertText(config, keys) {
  for (const key of keys) {
    if (config[key] != null && typeof config[key] !== "string") throw new Error(`${key}: must be text`);
  }
}

// Base for every card: config, its editor, language, loading and live updates.
class FitnessCard extends HTMLElement {
  // The visual editor, with a field for each of the card's static `options`.
  static getConfigElement() {
    const editor = document.createElement(EDITOR);
    editor.options = this.options;
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
    if (this._hass && this._card && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
    const unsubscribe = this._unsubscribe;
    this._unsubscribe = null;
    unsubscribe?.then((stop) => stop?.()).catch(() => {});
    clearTimeout(this._retry);
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLE}${this.constructor.style}</style><ha-card></ha-card>`;
    this._card = root.querySelector("ha-card");
    root.addEventListener("click", (e) => this._onEvent(e, "click"));
    root.addEventListener("input", (e) => this._onEvent(e, "input"));
    root.addEventListener("change", (e) => this._onEvent(e, "change"));
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
  // not_loaded, so try again shortly.
  async _start() {
    clearTimeout(this._retry);
    try {
      await this._load();
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
      .subscribeMessage((event) => this._changed(event), { type: "fork_and_scale/subscribe" })
      .catch(() => {
        this._unsubscribe = null;
      });
  }

  _showError(err, key = "error_failed") {
    if (!this._panel) return;
    this._panel.error = fill(this._t[key], { message: err?.message ?? "" });
    this._renderPanel();
  }

  get _scanner() {
    return scannerFor(this._hass);
  }

  // Scan a barcode with whatever this device offers; null if cancelled.
  async _scan() {
    const t = this._t;
    try {
      if (this._scanner === "app") return await scanWithApp(this._hass.auth.external, t);
      this._scanAbort = new AbortController();
      return await scanWithCamera(this._card.querySelector(".scanner"), t, this._scanAbort.signal);
    } catch (err) {
      this._showError(err, "camera_failed");
      return null;
    }
  }

  // `food` filled from its barcode. Returns {food} and either a note, an
  // error, or the saved food that already has the barcode.
  async _lookUp(food) {
    const t = this._t;
    const code = (food.barcode ?? "").trim();
    if (!BARCODE.test(code)) return { food, error: t.error_barcode };
    const saved = await this._call({ type: "fork_and_scale/food/barcode", barcode: code }).catch(() => null);
    if (saved && saved.id !== food.id) return { food, saved, note: fill(t.already_saved, { name: saved.name }) };
    try {
      const found = await lookUpBarcode(code, t.serving);
      if (!found) return { food: { ...food, barcode: code }, error: fill(t.off_not_found, { code }) };
      return { food: mergeFood(food, found), note: t.off_filled };
    } catch (err) {
      return { food, error: fill(t.off_failed, { message: err?.message ?? "" }) };
    }
  }

  // A product picked from a search of Open Food Facts, looked up by its
  // barcode for current values. If that fails, the food is what the search
  // found, with a warning. Returns what _lookUp does, or {food, warning}.
  async _lookUpPicked(product) {
    const looked = await this._lookUp({ barcode: product.code, portions: [] });
    if (!looked.error) return looked;
    return { food: searchedFood(product, offLanguage(this._locale), this._t.serving), warning: this._t.off_stale };
  }

  // Add the next page of Open Food Facts' products for `off.query` to `off`,
  // redrawing with _renderOff as it goes.
  async _searchOff(off) {
    Object.assign(off, { busy: true, error: null });
    this._renderOff();
    try {
      const found = await this._call({
        type: "fork_and_scale/openfoodfacts/search",
        query: off.query,
        language: offLanguage(this._locale),
        page: off.page + 1,
      });
      off.products.push(...found.products);
      off.more = found.more;
      off.page += 1;
    } catch (err) {
      off.error = err?.message ?? "";
    }
    off.busy = false;
    this._renderOff();
  }

  // Send a command; on failure show its error in the open panel.
  async _send(message, errorKey) {
    try {
      return { ok: true, result: await this._call(message) };
    } catch (err) {
      this._showError(err, errorKey?.(err) ?? "error_failed");
      return { ok: false };
    }
  }
}
