// Base for the cards with a food form, the food diary and saved foods.
// Errors show in the card's open panel, `_panel`, which it draws with
// `_renderPanel`.
class FoodCard extends FitnessCard {
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
