class FoodsCard extends FoodCard {
  static style = `
    .list { display: flex; flex-direction: column; max-height: 420px; overflow-y: auto; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 8px; width: 100%; text-align: left; padding: 8px 4px; border-top: 1px solid var(--divider-color); border-radius: 0; }
    .row small { color: var(--secondary-text-color); }
    .off { display: flex; flex-direction: column; }
    .panel { border-top: 1px solid var(--divider-color); padding-top: 12px; display: flex; flex-direction: column; gap: 12px; }
  `;

  static options = ["title", "locale"];

  getCardSize() {
    return 6;
  }

  async _load() {
    this._query ??= "";
    this._foods = await this._call({ type: "fork_and_scale/food/search", query: this._query.trim(), limit: 100 });
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
      <div class="panel" hidden></div><div class="list"></div><div class="off"></div>`;
    this._renderList();
    this._renderOff();
    this._renderPanel();
  }

  _renderList() {
    const list = this._card?.querySelector(".list");
    if (list) list.innerHTML = foodsListHTML(this._foods, this._query, this._locale, this._t);
  }

  _renderOff() {
    const box = this._card?.querySelector(".off");
    if (box) box.innerHTML = offSearchHTML(this._query, this._off, offLanguage(this._locale), this._locale, this._t);
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
         <button class="text" data-action="close">${esc(t.cancel)}</button><button class="danger" data-action="really-delete">${esc(t.yes_delete)}</button>`
      : `${p.food.id ? `<button class="text" data-action="delete">${esc(t.delete)}</button>` : ""}
         <button class="text" data-action="close">${esc(t.cancel)}</button><button class="fill" data-action="save">${esc(t.save_food)}</button>`;
    panel.innerHTML = `<div class="title">${esc(p.food.id ? p.food.name : t.tab_new)}</div>${foodFormHTML(p.food, t, Boolean(this._scanner))}
      ${p.note ? `<div class="note">${esc(p.note)}</div>` : ""}${p.warning ? `<div class="warning">${esc(p.warning)}</div>` : ""}${p.error ? `<div class="error">${esc(p.error)}</div>` : ""}<div class="actions">${buttons}</div>`;
  }

  // Fill the form from its barcode, or open the saved food that has it.
  async _fillFromBarcode() {
    const looked = await this._lookUp(this._panel.food);
    this._panel = looked.saved
      ? { food: looked.saved, note: looked.note }
      : { ...this._panel, food: looked.food, note: looked.note ?? null, warning: null, error: looked.error ?? null };
    this._renderPanel();
  }

  // Keep what has been typed, and the food being edited, across a redraw.
  _keepForm() {
    this._panel.food = { ...readFoodForm(this._card).food, id: this._panel.food.id };
  }

  static actions = {
    "click:new"() {
      this._panel = { food: { portions: [] } };
      this._renderPanel();
      this._card.querySelector('.foodform [data-field="name"]')?.focus?.();
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
      this._renderOff();
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => this._refresh(), SEARCH_DELAY_MS);
    },
    "click:off-search"() {
      this._off = { query: this._query.trim(), products: [], page: 0, more: false };
      this._searchOff(this._off);
    },
    "click:off-next"() {
      this._searchOff(this._off);
    },
    // Opens New food, filled in, or the saved food with the product's barcode.
    async "click:off-pick"(el) {
      const product = this._off.products.find((x) => x.code === el.dataset.code);
      const looked = await this._lookUpPicked(product);
      this._panel = looked.saved
        ? { food: looked.saved, note: looked.note }
        : { food: looked.food, note: looked.note ?? null, warning: looked.warning ?? null };
      this._renderPanel();
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
      const { food, error } = readFoodForm(this._card);
      this._panel.food = { ...food, id };
      if (error) return this._showError(null, error);
      const message = id ? { type: "fork_and_scale/food/update", food_id: id, ...food } : { type: "fork_and_scale/food/add", ...food };
      const sent = await this._send(message, barcodeError);
      if (sent.ok) {
        this._panel = null;
        this._renderPanel();
      }
    },
    "click:delete"() {
      this._panel.confirming = true;
      this._renderPanel();
    },
    async "click:lookup"() {
      this._keepForm();
      await this._fillFromBarcode();
    },
    async "click:scan"() {
      this._keepForm();
      const code = await this._scan();
      if (!code) return;
      this._panel.food.barcode = code;
      await this._fillFromBarcode();
    },
    "click:stop-scan"() {
      this._scanAbort?.abort();
    },
    async "click:really-delete"() {
      const sent = await this._send({ type: "fork_and_scale/food/delete", food_id: this._panel.food.id });
      if (sent.ok) {
        this._panel = null;
        this._renderPanel();
      }
    },
  };
}

function foodsListHTML(foods, query, locale, t) {
  if (!foods.length) {
    return `<div class="muted">${esc(query.trim() ? fill(t.no_results, { query: query.trim() }) : t.foods_empty)}</div>`;
  }
  return foods
    .map(
      (f) => `<button class="row" data-action="edit" data-id="${f.id}"><span>${esc(f.name)}${f.barcode ? ` <small>${esc(f.barcode)}</small>` : ""}</span>
        <small class="num">${esc(fill(t.per_100g_value, { kcal: number(f.kcal, locale) }))}</small></button>`,
    )
    .join("");
}
