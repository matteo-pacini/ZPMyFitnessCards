class FoodDiaryCard extends FoodCard {
  static style = `${super.style}
    .summary { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; align-items: center; text-align: center; gap: 4px; }
    .summary b { display: block; font-size: 1.3rem; font-weight: var(--ha-font-weight-medium, 500); }
    .summary small, .macro small { color: var(--secondary-text-color); font-size: var(--ha-font-size-xs, 0.75rem); }
    .body { display: flex; flex-direction: column; gap: 14px; }
    .summary .op { color: var(--secondary-text-color); font-size: 1.3rem; align-self: start; }
    .summary .left b { color: var(--success-color, var(--green-color)); }
    .summary .over b { color: var(--error-color); }
    .macros { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .macro { display: flex; flex-direction: column; gap: 4px; font-size: var(--ha-font-size-s, 0.875rem); }
    .bar { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
    .bar i { display: block; height: 100%; border-radius: 3px; }
    .protein i { background: var(--pink-color, var(--accent-color)); }
    .carbs i { background: var(--amber-color, var(--warning-color)); }
    .fat i { background: var(--deep-purple-color, var(--primary-color)); }
    .macro.over i { background: var(--error-color); }
    .meal { border-top: 1px solid var(--divider-color); padding-top: 10px; display: flex; flex-direction: column; gap: 2px; }
    .mealhead { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; font-weight: var(--ha-font-weight-medium, 500); }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 8px; width: 100%; text-align: left; padding: 6px 4px; }
    .row .amount { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); margin-left: 6px; }
    .mealactions { display: flex; gap: 12px; }
    .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--divider-color); }
    .tabs button { padding: 8px 10px; border-radius: 6px 6px 0 0; color: var(--secondary-text-color); }
    .tabs button[aria-selected="true"] { color: var(--primary-color); box-shadow: inset 0 -2px 0 var(--primary-color); }
    .searchrow { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; }
    .results, .off { display: flex; flex-direction: column; max-height: 240px; overflow-y: auto; }
    .results .row small, .off .row small { color: var(--secondary-text-color); }
    .results .row[aria-pressed="true"] { background: var(--secondary-background-color); }
    .picked { display: flex; flex-direction: column; gap: 10px; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chips button { border: 1px solid var(--divider-color); border-radius: 16px; padding: 4px 10px; font-size: var(--ha-font-size-s, 0.875rem); }
    .preview { display: grid; grid-template-columns: repeat(4, 1fr); text-align: center; gap: 4px;
      background: var(--secondary-background-color); border-radius: 8px; padding: 8px 4px; }
    .preview small { display: block; color: var(--secondary-text-color); font-size: var(--ha-font-size-xs, 0.75rem); }
  `;

  static options = ["person", "title", "locale"];

  getCardSize() {
    return 8;
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener(OPEN_DAY, this._openDay);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener(OPEN_DAY, this._openDay);
  }

  _openDay = (event) => {
    if (this._person && event.detail.person === this._person.id) this._goTo(event.detail.day);
  };

  async _load() {
    const people = await this._call({ type: "fork_and_scale/people" });
    this._person = findPerson(people, this._config, this._hass);
    this._day ??= this._today;
    this._data = this._person ? await this._fetchDay() : null;
  }

  _fetchDay() {
    return this._call({ type: "fork_and_scale/day", person: this._person.id, day: this._day });
  }

  async _reloadDay() {
    try {
      this._data = await this._fetchDay();
      this._renderBody();
    } catch {
      this._start();
    }
  }

  _changed(event) {
    if (event.person === null) {
      if (this._panel?.kind === "add" && this._panel.tab === "search") this._search();
    } else if (this._person && event.person === this._person.id) {
      this._reloadDay();
    }
  }

  _render() {
    if (!this._card) return;
    const t = this._t;
    const title = `<div class="title">${esc(this._config.title || t.title_diary)}</div>`;
    if (!this._person) {
      let message = t.loading;
      if (this._failure) message = fill(t.error_failed, { message: this._failure.message ?? "" });
      else if (this._data === null) message = this._config.person ? fill(t.unknown_person, { name: this._config.person }) : t.no_person;
      this._card.innerHTML = `${title}<div class="${message === t.loading ? "muted" : "error"}">${esc(message)}</div>`;
      return;
    }
    this._card.innerHTML = `<div class="head"></div><div class="body"></div><div class="panel" hidden></div>`;
    this._renderHead();
    this._renderBody();
    this._renderPanel();
  }

  _renderHead() {
    const t = this._t;
    const today = this._today;
    this._card.querySelector(".head").innerHTML = `
      <div><div class="title">${esc(this._config.title || t.title_diary)}</div><div class="sub person">${esc(this._person.name)}</div></div>
      <div class="nav">
        <button class="icon" data-action="prev" aria-label="${esc(t.previous_day)}">‹</button>
        <span class="label">${esc(dayLabel(this._day, today, this._locale, t))}</span>
        <button class="icon" data-action="next" aria-label="${esc(t.next_day)}"${this._day >= today ? " disabled" : ""}>›</button>
        <input type="date" data-action="pick-day" value="${this._day}" max="${today}" aria-label="${esc(t.pick_day)}">
      </div>`;
  }

  _renderBody() {
    const body = this._card?.querySelector(".body");
    if (body && this._data) body.innerHTML = diaryBodyHTML(this._data, this._t, this._locale);
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
    const error = p.error ? `<div class="error">${esc(p.error)}</div>` : "";
    if (p.kind === "edit") panel.innerHTML = editPanelHTML(p, this._locale, t) + error;
    else if (p.kind === "copy") panel.innerHTML = copyPanelHTML(p, this._today, t) + error;
    else {
      const warning = p.warning ? `<div class="warning">${esc(p.warning)}</div>` : "";
      panel.innerHTML = addPanelHTML(p, t, Boolean(this._scanner)) + (p.note ? `<div class="note">${esc(p.note)}</div>` : "") + warning + error;
    }
    if (p.kind === "add" && p.tab === "search") {
      this._renderResults();
      this._renderOff();
      this._renderPicked();
    }
  }

  _renderResults() {
    const box = this._card.querySelector(".results");
    const p = this._panel;
    if (!box || !p) return;
    const t = this._t;
    const query = p.query.trim();
    const foods = p.results ?? [];
    if (!foods.length) {
      const empty = p.results === undefined ? t.loading : query ? fill(t.no_results, { query }) : t.no_recent;
      const lookUp = p.results && BARCODE.test(query)
        ? `<button class="text" data-action="lookup-query">${esc(fill(t.look_up_barcode, { code: query }))}</button>`
        : "";
      box.innerHTML = `<div class="muted">${esc(empty)}</div>${lookUp}`;
      return;
    }
    box.innerHTML =
      `<div class="sub">${esc(query ? t.results : t.recent)}</div>` +
      foods
        .map(
          (f) => `<button class="row" data-action="choose" data-id="${f.id}" aria-pressed="${p.food?.id === f.id}">
            <span>${esc(f.name)}</span><small class="num">${esc(fill(t.per_100g_value, { kcal: number(f.kcal, this._locale) }))}</small></button>`,
        )
        .join("");
  }

  _renderOff() {
    const box = this._card?.querySelector(".panel .off");
    const p = this._panel;
    if (box && p) box.innerHTML = offSearchHTML(p.query, p.off, this._locale, this._t);
  }

  _renderPicked() {
    const box = this._card.querySelector(".picked");
    const p = this._panel;
    if (!box) return;
    if (!p.food) {
      box.innerHTML = "";
      return;
    }
    const t = this._t;
    const portions = (p.food.portions ?? [])
      .map((q) => `<button data-action="portion" data-grams="${q.grams}">${esc(q.name)} · ${number(q.grams, this._locale, 1)} g</button>`)
      .join("");
    box.innerHTML = `<div><b>${esc(p.food.name)}</b></div>
      <div class="grid">
        <label>${esc(t.grams)}<input data-action="grams" data-field="grams" type="number" min="0" step="any" inputmode="decimal" value="${p.grams ?? ""}"></label>
        <label>${esc(t.meal)}<select data-action="meal" data-field="meal">${optionList(MEALS, t, p.meal)}</select></label>
      </div>
      ${portions ? `<div class="chips">${portions}</div>` : ""}
      <div class="preview num"></div>
      <div class="actions"><button class="fill" data-action="add-entry">${esc(fill(t.add_to_meal, { meal: t[p.meal] }))}</button></div>`;
    this._renderPreview();
  }

  _renderPreview() {
    const box = this._card.querySelector(".preview");
    const p = this._panel;
    if (!box || !p?.food) return;
    box.innerHTML = previewHTML(p.food, p.grams, this._locale, this._t);
    this._card.querySelector('[data-action="add-entry"]').disabled = !(p.grams > 0);
  }

  _openPanel(panel) {
    this._panel = panel;
    this._renderPanel();
    if (panel.kind === "add" && panel.tab === "search") this._search();
    const first = this._card.querySelector(".panel input:not([type=date]), .panel select");
    first?.focus?.();
  }

  _closePanel() {
    this._panel = null;
    this._renderPanel();
  }

  async _search() {
    const p = this._panel;
    const query = p.query.trim();
    try {
      const results = query
        ? await this._call({ type: "fork_and_scale/food/search", query })
        : await this._call({ type: "fork_and_scale/food/recent", person: this._person.id });
      if (this._panel === p && p.query.trim() === query) {
        p.results = results;
        this._renderResults();
      }
    } catch (err) {
      this._showError(err);
    }
  }

  _field(key) {
    return this._card.querySelector(`.panel [data-field="${key}"]`);
  }

  // Fill the New food form from its barcode, or choose the saved food that has it.
  async _fillNewFood() {
    const p = this._panel;
    this._showLookedUp(p, await this._lookUp(p.newFood));
  }

  // Show in panel `p` what _lookUp or _lookUpPicked found, if `p` is still open.
  _showLookedUp(p, looked) {
    if (this._panel !== p) return;
    if (looked.saved) {
      Object.assign(p, { tab: "search", query: looked.saved.name, results: [looked.saved], food: looked.saved, grams: looked.saved.portions[0]?.grams ?? 100, note: looked.note, warning: null, error: null });
    } else {
      Object.assign(p, { newFood: looked.food, note: looked.note ?? null, warning: looked.warning ?? null, error: looked.error ?? null });
    }
    this._renderPanel();
  }

  async _goTo(day) {
    if (day > this._today) return;
    this._day = day;
    this._panel = null;
    this._renderHead();
    this._renderPanel();
    await this._reloadDay();
  }

  static actions = {
    "click:prev"() {
      this._goTo(shiftDay(this._day, -1));
    },
    "click:next"() {
      this._goTo(shiftDay(this._day, 1));
    },
    "change:pick-day"(el) {
      if (el.value) this._goTo(el.value);
    },
    "click:add"(el) {
      this._openPanel({ kind: "add", meal: el.dataset.meal, tab: "search", query: "" });
    },
    "click:copy"(el) {
      this._openPanel({ kind: "copy", meal: el.dataset.meal, fromDay: shiftDay(this._day, -1), fromMeal: el.dataset.meal });
    },
    "click:entry"(el) {
      const entry = this._data.entries.find((e) => String(e.id) === el.dataset.id);
      if (entry) this._openPanel({ kind: "edit", entry });
    },
    "click:close"() {
      this._closePanel();
    },
    "click:tab"(el) {
      const p = this._panel;
      p.tab = el.dataset.tab;
      p.error = null;
      p.note = null;
      p.warning = null;
      this._renderPanel();
      if (p.tab === "search") this._search();
    },
    "input:query"(el) {
      this._panel.query = el.value;
      this._renderOff();
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => this._search(), SEARCH_DELAY_MS);
    },
    "click:off-search"() {
      const p = this._panel;
      p.off = { query: p.query.trim(), products: [], page: 0, more: false };
      this._searchOff(p.off);
    },
    "click:off-next"() {
      this._searchOff(this._panel.off);
    },
    async "click:off-pick"(el) {
      const p = this._panel;
      const product = p.off.products.find((x) => x.code === el.dataset.code);
      Object.assign(p, { tab: "new", newFood: { barcode: product.code, portions: [] } });
      this._showLookedUp(p, await this._lookUpPicked(product));
    },
    "click:choose"(el) {
      const p = this._panel;
      p.food = p.results.find((f) => String(f.id) === el.dataset.id);
      p.grams = p.food.portions?.[0]?.grams ?? 100;
      this._renderResults();
      this._renderPicked();
      this._field("grams")?.focus?.();
    },
    "input:grams"(el) {
      this._panel.grams = numberValue(el);
      this._renderPreview();
    },
    "change:meal"(el) {
      this._panel.meal = el.value;
      this._renderPicked();
    },
    "click:portion"(el) {
      this._panel.grams = Number(el.dataset.grams);
      this._renderPicked();
    },
    async "click:add-entry"() {
      const p = this._panel;
      if (!(p.grams > 0)) return this._showError(null, "error_amount");
      const sent = await this._send({
        type: "fork_and_scale/entry/add",
        person: this._person.id,
        day: this._day,
        meal: p.meal,
        food_id: p.food.id,
        grams: p.grams,
      });
      if (sent.ok) this._closePanel();
    },
    async "click:quick-add"() {
      const name = this._field("name").value.trim();
      const kcal = numberValue(this._field("kcal"));
      if (!name || kcal == null || kcal < 0) return this._showError(null, "error_quick");
      const macros = Object.fromEntries(MACROS.map((m) => [m, numberValue(this._field(m))]));
      const sent = await this._send({
        type: "fork_and_scale/entry/add",
        person: this._person.id,
        day: this._day,
        meal: this._field("meal").value,
        name,
        kcal,
        ...macros,
      });
      if (sent.ok) this._closePanel();
    },
    "click:add-portion"() {
      const p = this._panel;
      p.newFood = readFoodForm(this._card).food;
      p.newFood.portions.push({ name: "", grams: null });
      this._renderPanel();
    },
    "click:remove-portion"(el) {
      const p = this._panel;
      p.newFood = readFoodForm(this._card).food;
      p.newFood.portions.splice(Number(el.dataset.index), 1);
      this._renderPanel();
    },
    async "click:scan"() {
      const p = this._panel;
      if (p.tab === "new") p.newFood = readFoodForm(this._card).food;
      const code = await this._scan();
      if (!code || this._panel !== p) return;
      if (p.tab === "new") {
        p.newFood.barcode = code;
        return this._fillNewFood();
      }
      p.query = code;
      p.results = undefined;
      this._renderPanel();
      await this._search();
      // A saved food with this barcode is the one to log.
      if (p.results?.length === 1 && p.results[0].barcode === code) {
        p.food = p.results[0];
        p.grams = p.food.portions?.[0]?.grams ?? 100;
        this._renderPicked();
      }
    },
    "click:stop-scan"() {
      this._scanAbort?.abort();
    },
    async "click:lookup"() {
      this._panel.newFood = readFoodForm(this._card).food;
      await this._fillNewFood();
    },
    async "click:lookup-query"() {
      const p = this._panel;
      p.tab = "new";
      p.newFood = { barcode: p.query.trim(), portions: [] };
      await this._fillNewFood();
    },
    async "click:save-new-food"() {
      const p = this._panel;
      const { food, error } = readFoodForm(this._card);
      p.newFood = food;
      if (error) return this._showError(null, error);
      const sent = await this._send({ type: "fork_and_scale/food/add", ...food }, barcodeError);
      if (!sent.ok) return;
      const saved = sent.result;
      Object.assign(p, { tab: "search", query: saved.name, results: [saved], food: saved, grams: saved.portions[0]?.grams ?? 100, newFood: null, warning: null, error: null });
      this._renderPanel();
    },
    async "click:save-edit"() {
      const p = this._panel;
      const field = p.entry.grams != null ? "grams" : "kcal";
      const amount = numberValue(this._field(field));
      if (amount == null || amount <= 0) return this._showError(null, "error_amount");
      const sent = await this._send({ type: "fork_and_scale/entry/update", entry_id: p.entry.id, meal: this._field("meal").value, [field]: amount });
      if (sent.ok) this._closePanel();
    },
    "click:delete-entry"() {
      this._panel.confirming = true;
      this._renderPanel();
    },
    async "click:really-delete"() {
      const sent = await this._send({ type: "fork_and_scale/entry/delete", entry_id: this._panel.entry.id });
      if (sent.ok) this._closePanel();
    },
    async "click:do-copy"() {
      const sent = await this._send({
        type: "fork_and_scale/meal/copy",
        person: this._person.id,
        from_day: this._field("from_day").value,
        from_meal: this._field("from_meal").value,
        to_day: this._day,
        to_meal: this._panel.meal,
      });
      if (!sent.ok) return;
      if (sent.result.length) this._closePanel();
      else this._showError(null, "nothing_to_copy");
    },
  };
}

// The summary and meals of one day, from fork_and_scale/day.
function diaryBodyHTML(data, t, locale) {
  const sums = totals(data.entries);
  const goals = data.goals;
  let summary;
  if (goals) {
    const left = goals.kcal - sums.kcal;
    summary = `<div class="summary num">
        <div><b>${number(goals.kcal, locale)}</b><small>${esc(t.goal)}</small></div><span class="op">−</span>
        <div><b>${number(sums.kcal, locale)}</b><small>${esc(t.food)}</small></div><span class="op">=</span>
        <div class="${left < 0 ? "over" : "left"}"><b>${number(Math.abs(left), locale)}</b><small>${esc(left < 0 ? t.over : t.remaining)}</small></div>
      </div>
      <div class="macros num">${MACROS.map((m) => {
        const share = goals[m] > 0 ? sums[m] / goals[m] : 0;
        return `<div class="macro ${m}${share > 1 ? " over" : ""}"><small>${esc(t[m])}</small>
          <div class="bar"><i style="width:${Math.min(share, 1) * 100}%"></i></div>
          <span>${number(sums[m], locale)} / ${number(goals[m], locale)} g</span></div>`;
      }).join("")}</div>`;
  } else {
    summary = `<div class="summary num"><div></div><span></span><div><b>${number(sums.kcal, locale)}</b><small>${esc(t.food)}</small></div></div>`;
  }
  const meals = MEALS.map((meal) => {
    const entries = data.entries.filter((e) => e.meal === meal);
    const rows = entries
      .map(
        (e) => `<button class="row" data-action="entry" data-id="${e.id}">
          <span>${esc(e.name)}${e.grams != null ? `<span class="amount num">${number(e.grams, locale, 1)} g</span>` : ""}</span>
          <span class="num">${number(e.kcal, locale)}</span></button>`,
      )
      .join("");
    return `<div class="meal" data-meal="${meal}">
      <div class="mealhead"><span>${esc(t[meal])}</span><span class="sub num">${entries.length ? `${number(totals(entries).kcal, locale)} ${esc(t.kcal)}` : ""}</span></div>
      ${rows || `<div class="muted">${esc(t.nothing_logged)}</div>`}
      <div class="mealactions">
        <button class="text" data-action="add" data-meal="${meal}">+ ${esc(t.add_food)}</button>
        <button class="text" data-action="copy" data-meal="${meal}">${esc(t.copy)}</button>
      </div></div>`;
  }).join("");
  return summary + meals;
}

function previewHTML(food, grams, locale, t) {
  const values = grams > 0 ? scaled(food, grams) : null;
  return ["kcal", ...MACROS]
    .map((n) => `<div><b>${values ? number(values[n], locale, n === "kcal" ? 0 : 1) : "–"}</b><small>${esc(n === "kcal" ? t.kcal : `${t[n]} (g)`)}</small></div>`)
    .join("");
}

function addPanelHTML(p, t, scan = false) {
  const tabs = ["search", "quick", "new"]
    .map((tab) => `<button data-action="tab" data-tab="${tab}" role="tab" aria-selected="${p.tab === tab}">${esc(t[`tab_${tab}`])}</button>`)
    .join("");
  const cancel = `<button class="text" data-action="close">${esc(t.cancel)}</button>`;
  let content;
  if (p.tab === "search") {
    const scanButton = scan ? `<button class="text" data-action="scan">${esc(t.scan)}</button>` : "";
    content = `<div class="searchrow"><input type="search" data-action="query" value="${esc(p.query)}" placeholder="${esc(t.search_placeholder)}" aria-label="${esc(t.search_placeholder)}">${scanButton}</div>
      <div class="scanner" hidden></div><div class="results"></div><div class="off"></div><div class="picked"></div>`;
  } else if (p.tab === "quick") {
    const n = (key, label) => `<label>${esc(label)}<input data-field="${key}" type="number" min="0" step="any" inputmode="decimal"></label>`;
    content = `<div class="grid"><label>${esc(t.name)}<input data-field="name"></label>${n("kcal", t.kcal)}</div>
      <div class="grid">${MACROS.map((m) => n(m, `${t[m]} (g, ${t.optional})`)).join("")}</div>
      <label>${esc(t.meal)}<select data-field="meal">${optionList(MEALS, t, p.meal)}</select></label>
      <div class="actions">${cancel}<button class="fill" data-action="quick-add">${esc(t.add)}</button></div>`;
  } else {
    content = `${foodFormHTML(p.newFood ?? {}, t, scan)}
      <div class="actions">${cancel}<button class="fill" data-action="save-new-food">${esc(t.save_and_choose)}</button></div>`;
  }
  return `<div class="mealhead"><span>${esc(fill(t.add_to_meal, { meal: t[p.meal] }))}</span>${cancel}</div>
    <div class="tabs" role="tablist">${tabs}</div>${content}`;
}

function editPanelHTML(p, locale, t) {
  const e = p.entry;
  const amount =
    e.grams != null
      ? `<label>${esc(t.grams)}<input data-field="grams" type="number" min="0" step="any" inputmode="decimal" value="${e.grams}"></label>`
      : `<label>${esc(t.kcal)}<input data-field="kcal" type="number" min="0" step="any" inputmode="decimal" value="${e.kcal}"></label>`;
  const buttons = p.confirming
    ? `<span class="error">${esc(fill(t.really_delete, { name: e.name }))}</span>
       <button class="text" data-action="close">${esc(t.cancel)}</button><button class="danger" data-action="really-delete">${esc(t.yes_delete)}</button>`
    : `<button class="text" data-action="delete-entry">${esc(t.delete)}</button><button class="text" data-action="close">${esc(t.cancel)}</button>
       <button class="fill" data-action="save-edit">${esc(t.save)}</button>`;
  return `<div class="mealhead"><span>${esc(t.edit_entry)}: ${esc(e.name)}</span><span class="sub num">${number(e.kcal, locale)} ${esc(t.kcal)}</span></div>
    <div class="grid">${amount}<label>${esc(t.meal)}<select data-field="meal">${optionList(MEALS, t, e.meal)}</select></label></div>
    <div class="actions">${buttons}</div>`;
}

function copyPanelHTML(p, today, t) {
  return `<div class="mealhead"><span>${esc(fill(t.copy_title, { meal: t[p.meal] }))}</span></div>
    <div class="grid">
      <label>${esc(t.copy_from_day)}<input data-field="from_day" type="date" value="${p.fromDay}" max="${today}"></label>
      <label>${esc(t.copy_from_meal)}<select data-field="from_meal">${optionList(MEALS, t, p.fromMeal)}</select></label>
    </div>
    <div class="actions"><button class="text" data-action="close">${esc(t.cancel)}</button><button class="fill" data-action="do-copy">${esc(t.copy)}</button></div>`;
}
