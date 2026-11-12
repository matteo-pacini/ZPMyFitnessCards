// Panel `p`'s note, warning and error, those it has. With strings `t`, also
// Try again after a lookup that could not reach Open Food Facts (p.retry),
// and Choose it and Save anyway for a food saved already by name (p.taken).
function panelMessagesHTML(p, t) {
  const messages = ["note", "warning", "error"].map((kind) => (p[kind] ? `<div class="${kind}">${esc(p[kind])}</div>` : "")).join("");
  if (!t) return messages;
  const retry = p.retry ? `<button class="text" data-action="retry-lookup">${esc(t.try_again)}</button>` : "";
  const taken = p.taken
    ? `<button class="text" data-action="choose-taken">${esc(t.choose_it)}</button><button class="text" data-action="save-anyway">${esc(t.save_anyway)}</button>`
    : "";
  return messages + (retry || taken ? `<div class="inline">${retry}${taken}</div>` : "");
}

// `html` with panel `p`'s messages above its last row of buttons, so that
// they show beside what they are about; at its end if it has no buttons.
function withMessages(html, p, t) {
  const at = html.lastIndexOf('<div class="actions">');
  const messages = panelMessagesHTML(p, t);
  return at < 0 ? html + messages : html.slice(0, at) + messages + html.slice(at);
}

const cancelButtonHTML = (t) => `<button class="text" data-action="close">${esc(t.cancel)}</button>`;

// Base for the cards with a food form, the food diary and saved foods.
// Errors show in the card's open panel, `_panel`, which it draws with
// `_renderPanel`.
class FoodCard extends FitnessCard {
  static style = `${SAVED_MEAL_STYLE}
    .panel { border-top: 1px solid var(--divider-color); padding-top: 12px; display: flex; flex-direction: column; gap: 12px; }
    .portion { display: grid; grid-template-columns: 1fr 90px auto; gap: 8px; margin-bottom: 6px; }
    .barcodes { display: flex; gap: 12px; }
    .scanner video { width: 100%; max-height: 260px; object-fit: cover; border-radius: 8px; background: var(--secondary-background-color); }
    .note { color: var(--secondary-text-color); }
    .warning { color: var(--warning-color); }
    .row small { color: var(--secondary-text-color); }
    .off { display: flex; flex-direction: column; max-height: 240px; overflow-y: auto; }
    .finder { display: flex; flex-direction: column; gap: 8px; padding-bottom: 12px; border-bottom: 1px solid var(--divider-color); }
    .inline { display: flex; flex-wrap: wrap; gap: 12px; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chips button, .chip { border: 1px solid var(--divider-color); border-radius: 16px; padding: 4px 10px; font-size: var(--ha-font-size-s, 0.875rem); }
    .review { display: flex; flex-direction: column; gap: 8px; }
    .reviewhead { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
    .reviewhead small { display: block; color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); }
    .lookup { display: flex; align-items: center; gap: 10px; color: var(--secondary-text-color); }
    .lookup .text { margin-left: auto; }
    .spinner { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--divider-color); border-top-color: var(--primary-color);
      animation: spin 0.8s linear infinite; flex: none; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
  `;

  _showError(err, key = "error_failed") {
    if (!this._panel) return;
    this._panel.error = fill(this._t[key], { message: err?.message ?? "" });
    this._renderPanel();
    this._revealButtons();
  }

  // Scroll the open panel's last row of buttons into view, with the message
  // above it.
  _revealButtons() {
    const rows = this._card?.querySelectorAll(".panel .actions");
    rows?.[rows.length - 1]?.scrollIntoView?.({ block: "nearest" });
  }

  // Run `lookUp`, a lookup of barcode `code` for panel `p`. While it runs, the
  // panel shows "Looking up" with Cancel (p.lookup). Resolves to its result,
  // or null if Cancel, a newer lookup or the panel closing dropped it.
  async _lookUpFor(p, code, lookUp) {
    const lookup = { code };
    Object.assign(p, { lookup, note: null, warning: null, error: null, retry: null, taken: null });
    this._renderPanel();
    const looked = await lookUp();
    if (this._panel !== p || p.lookup !== lookup) return null;
    p.lookup = null;
    return looked;
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
  // error, or the saved food that already has the barcode. `retry` is set
  // when Open Food Facts could not be reached, so trying again may work.
  async _lookUp(food) {
    const t = this._t;
    const code = (food.barcode ?? "").trim();
    if (!BARCODE.test(code)) return { food, error: t.error_barcode };
    const saved = await this._call({ type: "metron/food/barcode", barcode: code }).catch(() => null);
    if (saved && saved.id !== food.id) return { food, saved, note: fill(t.already_saved, { name: saved.name }) };
    try {
      const found = await lookUpBarcode(code, t.serving);
      if (!found) return { food: { ...food, barcode: code }, error: fill(t.off_not_found, { code }) };
      return { food: mergeFood(food, found), note: t.off_filled };
    } catch (err) {
      return { food, error: fill(t.off_failed, { message: err?.message ?? "" }), retry: true };
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
        type: "metron/openfoodfacts/search",
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

// Handlers every card with a food form shares, for its static `actions`.
const FOOD_ACTIONS = {
  "click:cancel-lookup"() {
    this._panel.lookup = null;
    this._renderPanel();
  },
  "click:retry-lookup"() {
    this._lookUpBarcode(this._panel.retry);
  },
  // From a short check to the whole form.
  "click:edit-values"() {
    this._panel.review = false;
    this._renderPanel();
    this._card.querySelector('.foodform [data-field="name"]')?.focus?.();
  },
};
