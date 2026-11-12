class FoodsCard extends FoodCard {
  static style = `${super.style}
    .list { display: flex; flex-direction: column; max-height: 420px; overflow-y: auto; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 8px; width: 100%; text-align: left; padding: 8px 4px; border-top: 1px solid var(--divider-color); border-radius: 0; }
  `;

  static options = ["title", "locale"];

  getCardSize() {
    return 6;
  }

  async _load() {
    this._query ??= "";
    [this._people, this._foods] = await Promise.all([
      this._call({ type: "metron/people" }),
      this._call({ type: "metron/food/search", query: this._query.trim(), limit: 100 }),
    ]);
  }

  _changed(event) {
    if (event.person === null) this._refresh();
  }

  async _refresh() {
    try {
      await this._load();
      this._renderList();
    } catch {
      this._start();
    }
  }

  _render() {
    if (!this._card) return;
    const t = this._t;
    const title = `<div class="title">${esc(this._config.title || t.title_foods)}</div>`;
    if (!this._foods) {
      const message = this._failure ? fill(t.error_failed, { message: this._failure.message ?? "" }) : t.loading;
      this._card.innerHTML = `${title}<div class="${this._failure ? "error" : "muted"}">${esc(message)}</div>`;
      return;
    }
    this._card.innerHTML = `<div class="head">${title}<button class="fill" data-action="new">+ ${esc(t.add_food)}</button></div>
      <input type="search" data-action="query" value="${esc(this._query)}" placeholder="${esc(t.search_placeholder)}" aria-label="${esc(t.search_placeholder)}">
      <div class="panel" hidden></div><div class="list"></div><div class="find"></div>`;
    this._renderList();
    this._renderPanel();
  }

  _renderList() {
    const list = this._card?.querySelector(".list");
    if (!list) return;
    list.innerHTML = foodsListHTML(this._foods, this._query, this._locale, this._t, this._people);
    this._card.querySelector(".find").innerHTML = offLinkHTML(this._query, this._foods.length > 0, this._t);
  }

  // A new food's search of Open Food Facts, when its panel is open.
  _renderOff() {
    const box = this._card?.querySelector(".panel .off");
    const p = this._panel;
    if (box && p) box.innerHTML = offSearchHTML(p.offQuery ?? "", p.off, this._locale, this._t);
  }

  _renderPanel() {
    const panel = this._card?.querySelector(".panel");
    if (!panel) return;
    const p = this._panel;
    panel.hidden = !p;
    if (!p) {
      panel.innerHTML = "";
      return;
    }
    const t = this._t;
    const buttons = p.confirming
      ? `<span class="error">${esc(fill(t.really_delete, { name: p.food.name }))}</span>
         ${cancelButtonHTML(t)}<button class="danger" data-action="really-delete">${esc(t.yes_delete)}</button>`
      : `${p.food.id ? `<button class="text" data-action="delete">${esc(t.delete)}</button>` : ""}
         ${cancelButtonHTML(t)}<button class="fill" data-action="save">${esc(t.save_food)}</button>`;
    const scan = Boolean(this._scanner);
    const finder = p.food.id ? "" : offFinderHTML(p.offQuery, t, scan);
    const body = p.review ? reviewHTML(p.food, this._locale, t) : foodFormHTML(p.food, t, scan, Boolean(p.food.id));
    const title = p.food.id ? `${esc(p.food.name)}${savedByPillHTML(p.food, this._people)}` : esc(t.tab_new);
    panel.innerHTML = `<div class="title">${title}</div>${p.lookup ? lookingUpHTML(p.lookup.code, t) : ""}${finder}${body}
      ${p.confirming ? deleteAlertHTML(p.meals, this._locale, t) : ""}${panelMessagesHTML(p, t)}<div class="actions">${buttons}</div>`;
    this._renderOff();
  }

  // The open new food's panel, keeping what was typed in it, or a new one.
  _newFoodPanel() {
    if (this._panel && !this._panel.food.id) this._keepForm();
    else this._panel = { food: { portions: [] } };
    return this._panel;
  }

  // Fill a new food in from barcode `code`, typed or scanned, opening one if
  // needed. Its search box empties: the barcode is in the food now.
  async _lookUpBarcode(code) {
    const p = this._newFoodPanel();
    // A product only checked, not edited, gives way to the new one.
    if (p.review) p.food = { portions: [] };
    Object.assign(p, { offQuery: "", off: null, review: false });
    p.food.barcode = code;
    await this._fillFromBarcode();
  }

  // Find `query` on Open Food Facts from a new food's form, opening one if
  // needed: look up a barcode, or search for a name.
  async _findOnOff(query) {
    if (BARCODE.test(query)) return this._lookUpBarcode(query);
    const p = this._newFoodPanel();
    const off = { query, products: [], page: 0, more: false };
    Object.assign(p, { offQuery: query, off, note: null, warning: null, error: null, retry: null, taken: null });
    this._renderPanel();
    await this._searchOff(off);
  }

  // Fill the food in from its barcode, or open the saved food that has it.
  async _fillFromBarcode() {
    const panel = this._panel;
    const code = (panel.food.barcode ?? "").trim();
    const looked = await this._lookUpFor(panel, code, () => this._lookUp(panel.food));
    if (looked) this._showLookedUp(looked, panel, code);
  }

  // Open what _lookUp or _lookUpPicked found for barcode `code`: the saved
  // food that has it, or `panel` with the food filled in, a new one as a
  // short check when Open Food Facts gave all it needs.
  _showLookedUp(looked, panel, code) {
    this._panel = looked.saved
      ? { food: looked.saved, note: looked.note }
      : {
          ...panel,
          food: looked.food,
          review: !panel.food.id && !looked.error && reviewable(looked.food),
          note: looked.note ?? null,
          warning: looked.warning ?? null,
          error: looked.error ?? null,
          retry: looked.retry ? code : null,
        };
    this._renderPanel();
    if (this._panel.error || this._panel.warning) this._revealButtons();
  }

  // Keep what has been typed, and the food being edited, across a redraw. A
  // short check has nothing typed.
  _keepForm() {
    if (this._panel.review) return;
    this._panel.food = { ...readFoodForm(this._card).food, id: this._panel.food.id };
  }

  // The food the panel shows: its short check, or what its form says, which
  // may not be filled in right.
  _readFood() {
    const p = this._panel;
    if (p.review) return { food: p.food, error: null };
    const { food, error } = readFoodForm(this._card);
    p.food = { ...food, id: p.food.id };
    return { food, error };
  }

  // Save the new food `food`, saved by the person linked to whoever is
  // logged in. A food saved already opens instead, with a warning, if it has
  // the barcode; if it has the name, the warning asks what to do.
  async _saveNew(food, anyway = false) {
    const p = this._panel;
    const t = this._t;
    const person = findPerson(this._people, {}, this._hass);
    try {
      await this._call({ type: "metron/food/add", ...food, ...(person && { person: person.id }), ...(anyway && { anyway }) });
      if (this._panel !== p) return;
      this._panel = null;
      this._renderPanel();
    } catch (err) {
      if (this._panel !== p) return;
      const taken = err?.translation_placeholders;
      if (err?.code === "barcode_taken" && taken) {
        const existing = await this._call({ type: "metron/food/barcode", barcode: food.barcode }).catch(() => null);
        if (existing && this._panel === p) {
          this._panel = { food: existing, warning: takenText(err.code, taken, this._people, t) };
          this._renderPanel();
          this._revealButtons();
          return;
        }
      }
      if (err?.code === "name_taken" && taken) {
        Object.assign(p, { taken, warning: takenText(err.code, taken, this._people, t), error: null });
        this._renderPanel();
        this._revealButtons();
        return;
      }
      this._showError(err, barcodeError(err));
    }
  }

  static actions = {
    ...FOOD_ACTIONS,
    "click:new"() {
      this._panel = { food: { portions: [] } };
      this._renderPanel();
      this._card.querySelector('.panel [data-action="off-query"]')?.focus?.();
    },
    "click:edit"(el) {
      const food = this._foods.find((f) => String(f.id) === el.dataset.id);
      this._panel = { food: JSON.parse(JSON.stringify(food)) };
      this._renderPanel();
    },
    "click:close"() {
      this._panel = null;
      this._renderPanel();
    },
    "input:query"(el) {
      this._query = el.value;
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => this._refresh(), SEARCH_DELAY_MS);
    },
    "click:off-find"(el) {
      this._findOnOff(el.dataset.query);
    },
    "input:off-query"(el) {
      this._panel.offQuery = el.value;
      this._renderOff();
    },
    "keydown:off-query"(el, event) {
      if (event.key === "Enter" && el.value.trim()) this._findOnOff(el.value.trim());
    },
    "click:off-next"() {
      this._searchOff(this._panel.off);
    },
    async "click:off-scan"() {
      const panel = this._panel;
      const code = await this._scan();
      if (code && this._panel === panel) await this._lookUpBarcode(code);
    },
    // Fills the new food in, or opens the saved food with the product's barcode.
    async "click:off-pick"(el) {
      const panel = this._panel;
      const product = panel.off.products.find((x) => x.code === el.dataset.code);
      const looked = await this._lookUpFor(panel, product.code, () => this._lookUpPicked(product));
      if (!looked) return;
      this._showLookedUp(looked, panel, product.code);
      this._card.querySelector('.foodform [data-field="name"]')?.focus?.();
    },
    "click:add-portion"() {
      this._keepForm();
      this._panel.food.portions.push({ name: "", grams: null });
      this._renderPanel();
    },
    "click:remove-portion"(el) {
      this._keepForm();
      this._panel.food.portions.splice(Number(el.dataset.index), 1);
      this._renderPanel();
    },
    async "click:save"() {
      const id = this._panel.food.id;
      const { food, error } = this._readFood();
      if (error) return this._showError(null, error);
      if (!id) return this._saveNew(food);
      const sent = await this._send({ type: "metron/food/update", food_id: id, ...food }, barcodeError);
      if (sent.ok) {
        this._panel = null;
        this._renderPanel();
      }
    },
    async "click:save-anyway"() {
      const { food, error } = this._readFood();
      if (error) return this._showError(null, error);
      Object.assign(this._panel, { taken: null, warning: null });
      await this._saveNew(food, true);
    },
    // Opens the food a name warning was about, instead of saving another.
    async "click:choose-taken"() {
      const p = this._panel;
      const { food_id: id, name } = p.taken;
      try {
        const found = await this._call({ type: "metron/food/search", query: name, limit: 100 });
        const food = found.find((f) => String(f.id) === id);
        if (this._panel !== p) return;
        if (!food) return this._showError(null, "error_failed");
        this._panel = { food: JSON.parse(JSON.stringify(food)) };
        this._renderPanel();
      } catch (err) {
        this._showError(err);
      }
    },
    // Asks first, naming the saved meals the food is in.
    async "click:delete"() {
      const p = this._panel;
      try {
        const meals = await this._call({ type: "metron/food/meals", food_id: p.food.id });
        if (this._panel !== p) return;
        Object.assign(p, { confirming: true, meals });
        this._renderPanel();
        this._revealButtons();
      } catch (err) {
        this._showError(err);
      }
    },
    async "click:lookup"() {
      this._keepForm();
      await this._fillFromBarcode();
    },
    async "click:scan"() {
      this._keepForm();
      const panel = this._panel;
      const code = await this._scan();
      if (!code || this._panel !== panel) return;
      panel.food.barcode = code;
      await this._fillFromBarcode();
    },
    "click:stop-scan"() {
      this._scanAbort?.abort();
    },
    async "click:really-delete"() {
      const sent = await this._send({ type: "metron/food/delete", food_id: this._panel.food.id });
      if (sent.ok) {
        this._panel = null;
        this._renderPanel();
      }
    },
  };
}

// What deleting a food would do to the saved meals it is in, `meals` from
// metron/food/meals: take it out of them, and delete those it empties.
function deleteAlertHTML(meals, locale, t) {
  if (!meals?.length) return "";
  const names = (list) => listText(list.map((m) => m.name), locale);
  const emptied = meals.filter((m) => m.emptied);
  return `<div class="alert">${esc(fill(t.food_in_meals, { meals: names(meals) }))}${
    emptied.length ? `<br><b>${esc(fill(t.meals_emptied, { meals: names(emptied) }))}</b>` : ""
  }</div>`;
}

// Saved foods as rows, each with who saved it when that is known.
function foodsListHTML(foods, query, locale, t, people = []) {
  if (!foods.length) {
    return `<div class="muted">${esc(query.trim() ? fill(t.no_results, { query: query.trim() }) : t.foods_empty)}</div>`;
  }
  return foods
    .map(
      (f) => `<button class="row" data-action="edit" data-id="${f.id}"><span>${esc(f.name)}${savedByPillHTML(f, people)}${f.barcode ? ` <small>${esc(f.barcode)}</small>` : ""}</span>
        <small class="num">${esc(fill(t.per_100g_value, { kcal: number(f.kcal, locale) }))}</small></button>`,
    )
    .join("");
}
