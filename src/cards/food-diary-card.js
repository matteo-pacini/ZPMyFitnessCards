class FoodDiaryCard extends ShowsPerson(FoodCard) {
  static style = `${super.style}
    .nav { display: flex; align-items: center; gap: 4px; }
    .nav .label { min-width: 6.5em; text-align: center; font-weight: var(--ha-font-weight-medium, 500); }
    .icon { width: 32px; height: 32px; font-size: 1.1rem; line-height: 1; }
    .icon:hover:not(:disabled) { background: var(--secondary-background-color); }
    /* Just a calendar button: the label beside it already shows the day. The
       card draws the icon, since not every browser draws one in a date input,
       and lays the input over it unseen, so that a tap anywhere opens the picker. */
    .calendar { position: relative; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; cursor: pointer; }
    .calendar svg { width: 20px; height: 20px; fill: currentColor; }
    .calendar:focus-within { outline: 2px solid var(--primary-color); outline-offset: 1px; }
    .calendar input { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; padding: 0; border: 0; opacity: 0; cursor: pointer; }
    .calendar input::-webkit-calendar-picker-indicator { position: absolute; inset: 0; width: auto; height: auto; margin: 0; padding: 0; cursor: pointer; }
    .summary { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; align-items: center; text-align: center; gap: 4px; }
    .summary.withactivity { grid-template-columns: 1fr auto 1fr auto 1fr auto 1fr; container-type: inline-size; }
    .summary b { display: block; font-size: 1.3rem; font-weight: var(--ha-font-weight-medium, 500); }
    /* A missing sensor is named by its entity ID, which has no spaces to break at. */
    .activity { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); overflow-wrap: anywhere; }
    .summary small, .macro small { color: var(--secondary-text-color); font-size: var(--ha-font-size-xs, 0.75rem); }
    .body { display: flex; flex-direction: column; gap: 14px; }
    .summary .op { color: var(--secondary-text-color); font-size: 1.3rem; align-self: start; }
    /* Four four-digit figures and three signs overflow a narrow card, as on a
       phone, at full size: a size down they fit from a 300 px card up. */
    @container (max-width: 320px) {
      .summary.withactivity b, .summary.withactivity .op { font-size: 1.05rem; }
    }
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
    .mealhead { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; font-weight: var(--ha-font-weight-medium, 500); }
    /* When the title does not fit beside them, as in German, they keep to the right. */
    .headactions { display: flex; gap: 4px; align-items: baseline; margin-left: auto; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 8px; width: 100%; text-align: left; padding: 6px 4px; }
    .row .amount { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); margin-left: 6px; }
    .mealactions { display: flex; flex-wrap: wrap; column-gap: 12px; }
    .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--divider-color); }
    .tabs button { padding: 8px 10px; border-radius: 6px 6px 0 0; color: var(--secondary-text-color); }
    .tabs button[aria-selected="true"] { color: var(--primary-color); box-shadow: inset 0 -2px 0 var(--primary-color); }
    .results { display: flex; flex-direction: column; }
    .results { max-height: 240px; overflow-y: auto; }
    .results .row[aria-pressed="true"] { background: var(--secondary-background-color); }
    .picked { display: flex; flex-direction: column; gap: 10px; }
    .allmeals { align-self: flex-start; }
  `;

  static options = ["person", "title", "locale"];
  static titleKey = "title_diary";

  getCardSize() {
    return 8;
  }

  // Home Assistant passes a new hass with every change of state. Of the day
  // drawn, only the activity line reads states, for the sensor's name, which
  // may change, or arrive only after the day was drawn. Then only the line
  // changes: redrawing the body on every hass would lose what has focus in it.
  set hass(hass) {
    super.hass = hass;
    const activity = this._data?.activity;
    const name = activity && sensorName(activity, hass.states);
    if (name === this._sensorName) return;
    this._sensorName = name;
    const line = this._card.querySelector(".body .activity");
    if (line) line.textContent = activityLine(activity, hass.states, this._person.name, this._locale, this._t);
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

  _load() {
    this._day ??= this._today;
    return super._load();
  }

  _fetch() {
    return this._call({ type: "metron/day", person: this._person.id, day: this._day });
  }

  // A diary on today moves to the new today; one on an earlier day stays there.
  _newDay() {
    if (this._day === this._fetchedOn) this._day = this._today;
    this._renderHead();
    this._refresh();
  }

  _changed(event) {
    if (event.person === null) {
      if (this._onSearchTab) {
        this._panel.meals = undefined;
        this._search();
      }
    } else if (this._person && event.person === this._person.id) {
      this._refresh();
    }
  }

  _render() {
    if (!this._card || this._renderNoPerson()) return;
    this._card.innerHTML = `<div class="head"></div><div class="body"></div><div class="panel" hidden></div>`;
    this._renderHead();
    this._renderBody();
    this._renderPanel();
  }

  _renderHead() {
    const t = this._t;
    const today = this._today;
    this._card.querySelector(".head").innerHTML = `
      <div>${this._titleHTML}<div class="sub person">${esc(this._person.name)}</div></div>
      <div class="nav">
        <button class="icon" data-action="prev" aria-label="${esc(t.previous_day)}">‹</button>
        <span class="label">${esc(dayLabel(this._day, today, this._locale, t))}</span>
        <button class="icon" data-action="next" aria-label="${esc(t.next_day)}"${this._day >= today ? " disabled" : ""}>›</button>
        <label class="icon calendar">${CALENDAR_SVG}<input type="date" data-action="pick-day" value="${this._day}" max="${today}" aria-label="${esc(t.pick_day)}"></label>
      </div>`;
  }

  _renderBody() {
    const body = this._card?.querySelector(".body");
    if (!body || !this._data) return;
    const { activity } = this._data;
    this._sensorName = activity && sensorName(activity, this._hass.states);
    body.innerHTML = diaryBodyHTML(this._data, this._t, this._locale, this._hass.states, this._person.name);
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
    let html;
    if (p.kind === "edit") html = editPanelHTML(p, this._locale, t);
    else if (p.kind === "copy") html = copyPanelHTML(p, this._today, t);
    else if (p.kind === "save-meal") html = saveMealPanelHTML(p, this._locale, t);
    else html = addPanelHTML(p, t, Boolean(this._scanner), this._locale);
    // On the Saved tab, what was chosen has the button: _renderPicked puts
    // the messages there.
    panel.innerHTML = this._onSearchTab && (p.food || p.chosen) ? html : withMessages(html, p, t);
    if (this._onSearchTab) {
      this._renderResults();
      this._renderPicked();
    }
    this._renderOff();
  }

  // Whether the open panel shows the add panel's search tab.
  get _onSearchTab() {
    return this._panel?.kind === "add" && this._panel.tab === "search";
  }

  _renderResults() {
    const box = this._card.querySelector(".results");
    const p = this._panel;
    if (!box || !p) return;
    box.innerHTML = resultsHTML(p, this._locale, this._t, this._people);
    this._card.querySelector(".find").innerHTML = p.results && !p.chosen ? offLinkHTML(p.query, p.results.length > 0, this._t) : "";
  }

  // The New food tab's search of Open Food Facts, when it shows.
  _renderOff() {
    const box = this._card?.querySelector(".panel .off");
    const p = this._panel;
    if (box && p) box.innerHTML = offSearchHTML(p.offQuery ?? "", p.off, this._locale, this._t);
  }

  _renderPicked() {
    const box = this._card.querySelector(".picked");
    if (!box) return;
    const p = this._panel;
    const html = p.chosen ? chosenMealHTML(p, this._locale, this._t, this._people) : pickedHTML(p, this._locale, this._t);
    box.innerHTML = html && withMessages(html, p, this._t);
    this._renderPreview();
  }

  _renderPreview() {
    const box = this._card.querySelector(".preview");
    const p = this._panel;
    if (!box || !p?.food) return;
    box.innerHTML = previewHTML(p.food, p.grams, this._locale, this._t);
    this._card.querySelector('[data-action="add-entry"]').disabled = !(p.grams > 0);
  }

  // The totals of what is ticked, and whether the button that takes it can be
  // pressed. Only these redraw, so the box just ticked keeps focus.
  _renderTicked() {
    const p = this._panel;
    const items = p.kind === "save-meal" ? p.entries : p.chosen.items;
    this._card.querySelector(".panel .preview").innerHTML = totalsHTML(ticked(items, p.ticks), this._locale, this._t);
    this._card.querySelector('.panel [data-action="save-meal"], .panel [data-action="log-meal"]').disabled = !p.ticks.some(Boolean);
  }

  _openPanel(panel) {
    this._scanAbort?.abort();
    this._panel = panel;
    this._renderPanel();
    if (this._onSearchTab) this._search();
    const first = this._card.querySelector(".panel input:not([type=date]), .panel select");
    first?.focus?.();
  }

  _closePanel() {
    this._scanAbort?.abort();
    this._panel = null;
    this._renderPanel();
  }

  // Send a command; close the panel once it succeeds, unless another took its place.
  async _sendAndClose(message) {
    const p = this._panel;
    const sent = await this._send(message);
    if (sent.ok && this._panel === p) this._closePanel();
  }

  // The Saved tab's saved foods for its query, or recent ones, and the meals
  // the person can see, unless the panel has them.
  async _search() {
    const p = this._panel;
    const query = p.query.trim();
    try {
      const [results, meals] = await Promise.all([
        query
          ? this._call({ type: "metron/food/search", query })
          : this._call({ type: "metron/food/recent", person: this._person.id }),
        p.meals ?? this._call({ type: "metron/meals", person: this._person.id }),
      ]);
      if (this._panel === p && p.query.trim() === query) {
        p.results = results;
        p.meals = meals;
        this._renderResults();
      }
    } catch (err) {
      this._showError(err);
    }
  }

  _field(key) {
    return this._card.querySelector(`.panel [data-field="${key}"]`);
  }

  // Keep what was typed or chosen in the open panel, which a redraw would
  // lose: for an error, or in the add panel for another tab, a scan or a lookup.
  _keepTyped() {
    const p = this._panel;
    if (p?.kind === "edit") {
      p.amount = this._field(amountField(p.entry)).value;
      p.meal = this._field("meal").value;
    }
    if (p?.kind === "copy") {
      p.fromDay = this._field("from_day").value;
      p.fromMeal = this._field("from_meal").value;
    }
    if (p?.kind !== "add") return;
    if (p.tab === "quick" && this._field("name")) {
      p.quick = Object.fromEntries(["name", "kcal", ...MACROS, "meal"].map((k) => [k, this._field(k).value]));
    }
    if (p.tab === "new" && this._card.querySelector(".foodform")) p.newFood = readFoodForm(this._card).food;
  }

  // Look up barcode `code`, scanned or typed: choose the saved food that has
  // it on the Saved tab, or fill in a new food from Open Food Facts on the New
  // food tab. The New food search box empties: the barcode is in the food now.
  // What was typed in the form stays; a product only checked, not edited,
  // gives way to the new one.
  async _lookUpBarcode(code) {
    const p = this._panel;
    this._keepTyped();
    const typed = p.review ? null : p.newFood;
    Object.assign(p, { offQuery: "", off: null, review: false });
    const food = { ...(typed ?? { portions: [] }), barcode: code };
    const looked = await this._lookUpFor(p, code, () => this._lookUp(food));
    if (looked) this._showLookedUp(p, looked, code);
  }

  // Find `query` on Open Food Facts from the New food tab, switching to it:
  // look up a barcode, or search for a name.
  async _findOnOff(query) {
    if (BARCODE.test(query)) return this._lookUpBarcode(query);
    const p = this._panel;
    this._keepTyped();
    const off = { query, products: [], page: 0, more: false };
    Object.assign(p, { tab: "new", offQuery: query, off, note: null, warning: null, error: null, retry: null, taken: null });
    this._renderPanel();
    await this._searchOff(off);
  }

  // Show in panel `p` what _lookUp or _lookUpPicked found for barcode
  // `code`: the saved food that has it, chosen, or the new food, as a short
  // check when Open Food Facts gave all it needs.
  _showLookedUp(p, looked, code) {
    if (looked.saved) {
      showSavedFood(p, looked.saved);
      p.note = looked.note;
    } else {
      Object.assign(p, {
        tab: "new",
        newFood: looked.food,
        review: !looked.error && reviewable(looked.food),
        note: looked.note ?? null,
        warning: looked.warning ?? null,
        error: looked.error ?? null,
        retry: looked.retry ? code : null,
      });
    }
    this._renderPanel();
    if (p.error || p.warning) this._revealButtons();
  }

  _chooseMeal(meal) {
    const p = this._panel;
    Object.assign(p, { chosen: meal, ticks: meal.items.map(() => true), food: null, error: null, note: null, warning: null });
    this._renderResults();
    this._renderPicked();
  }

  _chooseFood(food) {
    const p = this._panel;
    p.chosen = null;
    chooseFood(p, food);
    this._renderResults();
    this._renderPicked();
    this._field("grams")?.focus?.();
  }

  // Save food `food` from the New food tab, saved by the diary's person, and
  // choose it. A food saved already is chosen instead, with a warning, if it
  // has the barcode; if it has the name, the warning asks what to do.
  async _saveNewFood(p, food, anyway = false) {
    const t = this._t;
    try {
      const message = { type: "metron/food/add", ...food, person: this._person.id, ...(anyway && { anyway }) };
      const saved = await this._call(message);
      if (this._panel !== p) return;
      showSavedFood(p, saved);
      this._renderPanel();
    } catch (err) {
      if (this._panel !== p) return;
      const taken = err?.translation_placeholders;
      if (err?.code === "barcode_taken" && taken) {
        const existing = await this._call({ type: "metron/food/barcode", barcode: food.barcode }).catch(() => null);
        if (existing && this._panel === p) {
          showSavedFood(p, existing);
          p.warning = takenText(err.code, taken, this._people, t);
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

  // The new food the New food tab shows: its short check, or its form, which
  // may not be filled in right.
  _newFood() {
    const p = this._panel;
    if (p.review) return { food: p.newFood, error: null };
    const read = readFoodForm(this._card);
    p.newFood = read.food;
    return read;
  }

  async _goTo(day) {
    if (day > this._today) return;
    this._day = day;
    this._panel = null;
    this._renderHead();
    this._renderPanel();
    await this._refresh();
  }

  static actions = {
    ...FOOD_ACTIONS,
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
    "click:save-as-meal"(el) {
      const meal = el.dataset.meal;
      const entries = this._data.entries.filter((e) => e.meal === meal);
      this._openPanel({ kind: "save-meal", meal, entries, ticks: entries.map(() => true), name: "", share: false });
    },
    "input:meal-name"(el) {
      this._panel.name = el.value;
    },
    "keydown:meal-name"(el, event) {
      if (event.key === "Enter") this.constructor.actions["click:save-meal"].call(this);
    },
    "change:share"(el) {
      this._panel.share = el.checked;
    },
    "change:tick"(el) {
      this._panel.ticks[Number(el.dataset.index)] = el.checked;
      this._renderTicked();
    },
    "click:save-meal": writes(async function () {
      const p = this._panel;
      const name = p.name.trim();
      if (!p.ticks.some(Boolean)) return;
      if (!name) return this._showError(null, "error_meal_name");
      const items = ticked(p.entries, p.ticks).map((e) =>
        e.food_id != null ? { food_id: e.food_id, grams: e.grams } : { name: e.name, grams: e.grams, ...Object.fromEntries(NUTRIENTS.map((n) => [n, e[n]])) },
      );
      try {
        await this._call({ type: "metron/meal/add", name, owner: p.share ? null : this._person.id, items });
        if (this._panel === p) this._closePanel();
      } catch (err) {
        if (err?.code !== "meal_exists") return this._showError(err);
        p.error = mealExistsText(err, name, this._people, this._t);
        this._renderPanel();
        this._revealButtons();
      }
    }),
    "click:choose-meal"(el) {
      const p = this._panel;
      // Tapping the chosen meal again goes back to the results. It may be
      // gone from p.meals, if someone deleted it meanwhile.
      if (p.chosen && String(p.chosen.id) === el.dataset.id) {
        p.chosen = null;
        this._renderResults();
        this._renderPicked();
        return;
      }
      const meal = p.meals?.find((m) => String(m.id) === el.dataset.id);
      if (meal) this._chooseMeal(meal);
    },
    "click:all-meals"() {
      this._panel.allMeals = true;
      this._renderResults();
    },
    "click:log-meal": writes(async function () {
      const p = this._panel;
      const meal = p.chosen;
      if (!p.ticks.some(Boolean)) return;
      try {
        await this._call({
          type: "metron/meal/log",
          person: this._person.id,
          day: this._day,
          meal: p.meal,
          meal_id: meal.id,
          version: meal.version,
          items: ticked(meal.items, p.ticks).map((i) => i.id),
        });
        if (this._panel === p) this._closePanel();
      } catch (err) {
        if (err?.code !== "meal_changed") return this._showError(err);
        // Show the meals as they are now, to choose again.
        Object.assign(p, { chosen: null, meals: undefined, error: fill(this._t.meal_gone, { name: meal.name }) });
        this._renderPanel();
        this._revealButtons();
        await this._search();
      }
    }),
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
      this._scanAbort?.abort();
      this._keepTyped();
      Object.assign(p, { tab: el.dataset.tab, error: null, note: null, warning: null, retry: null, taken: null });
      this._renderPanel();
      if (p.tab === "search") this._search();
    },
    "input:query"(el) {
      const p = this._panel;
      p.query = el.value;
      if (p.chosen) {
        p.chosen = null;
        this._renderPicked();
      }
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => this._search(), SEARCH_DELAY_MS);
    },
    // With one saved meal or food matching, Enter chooses it.
    async "keydown:query"(el, event) {
      if (event.key !== "Enter") return;
      const p = this._panel;
      clearTimeout(this._searchTimer);
      p.query = el.value;
      await this._search();
      const query = p.query.trim();
      if (this._panel !== p || !query) return;
      const meals = (p.meals ?? []).filter((m) => nameMatches(m.name, query));
      const foods = p.results ?? [];
      if (meals.length + foods.length !== 1) return;
      if (meals.length) this._chooseMeal(meals[0]);
      else this._chooseFood(foods[0]);
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
    async "click:off-pick"(el) {
      const p = this._panel;
      const product = p.off.products.find((x) => x.code === el.dataset.code);
      const looked = await this._lookUpFor(p, product.code, () => this._lookUpPicked(product));
      if (!looked) return;
      this._showLookedUp(p, looked, product.code);
      if (p.tab === "new") this._field("name")?.focus?.();
    },
    "click:choose"(el) {
      const p = this._panel;
      this._chooseFood(p.results.find((f) => String(f.id) === el.dataset.id));
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
    "click:add-entry": writes(async function () {
      const p = this._panel;
      if (!(p.grams > 0)) return this._showError(null, "error_amount");
      await this._sendAndClose({
        type: "metron/entry/add",
        person: this._person.id,
        day: this._day,
        meal: p.meal,
        food_id: p.food.id,
        grams: p.grams,
      });
    }),
    "click:quick-add": writes(async function () {
      this._keepTyped();
      const name = this._field("name").value.trim();
      const kcal = numberValue(this._field("kcal"));
      if (!name || kcal == null || kcal < 0) return this._showError(null, "error_quick");
      const macros = Object.fromEntries(MACROS.map((m) => [m, numberValue(this._field(m))]));
      await this._sendAndClose({
        type: "metron/entry/add",
        person: this._person.id,
        day: this._day,
        meal: this._field("meal").value,
        name,
        kcal,
        ...macros,
      });
    }),
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
    // The one Scan, in the add panel's head, on every tab.
    async "click:scan"() {
      const p = this._panel;
      this._keepTyped();
      const code = await this._scan();
      if (this._panel !== p) return;
      // Cancelled, as with Back in the app's scanner: nothing changes.
      if (!code) return this._card.querySelector('.panel [data-action="scan"]')?.focus?.();
      await this._lookUpBarcode(code);
    },
    "click:stop-scan"() {
      this._scanAbort?.abort();
    },
    "click:save-new-food": writes(async function () {
      const p = this._panel;
      const { food, error } = this._newFood();
      if (error) return this._showError(null, error);
      await this._saveNewFood(p, food);
    }),
    "click:save-anyway": writes(async function () {
      const p = this._panel;
      const { food, error } = this._newFood();
      if (error) return this._showError(null, error);
      Object.assign(p, { taken: null, warning: null });
      await this._saveNewFood(p, food, true);
    }),
    // The food a name warning was about, chosen instead of saving another.
    async "click:choose-taken"() {
      const p = this._panel;
      const { food_id: id, name } = p.taken;
      try {
        const found = await this._call({ type: "metron/food/search", query: name, limit: 100 });
        const food = found.find((f) => String(f.id) === id);
        if (this._panel !== p) return;
        if (!food) return this._showError(null, "error_failed");
        showSavedFood(p, food);
        this._renderPanel();
      } catch (err) {
        this._showError(err);
      }
    },
    "click:save-edit": writes(async function () {
      const p = this._panel;
      this._keepTyped();
      const field = amountField(p.entry);
      const amount = numberValue(this._field(field));
      if (amount == null || amount <= 0) return this._showError(null, "error_amount");
      await this._sendAndClose({ type: "metron/entry/update", entry_id: p.entry.id, meal: this._field("meal").value, [field]: amount });
    }),
    "click:delete-entry"() {
      this._panel.confirming = true;
      this._renderPanel();
    },
    "click:really-delete": writes(async function () {
      await this._sendAndClose({ type: "metron/entry/delete", entry_id: this._panel.entry.id });
    }),
    "click:do-copy": writes(async function () {
      const p = this._panel;
      this._keepTyped();
      const sent = await this._send({
        type: "metron/meal/copy",
        person: this._person.id,
        from_day: this._field("from_day").value,
        from_meal: this._field("from_meal").value,
        to_day: this._day,
        to_meal: this._panel.meal,
      });
      if (!sent.ok || this._panel !== p) return;
      if (sent.result.length) this._closePanel();
      else this._showError(null, "nothing_to_copy");
    }),
  };
}

// A calendar page with a day marked, drawn in the text's colour.
const CALENDAR_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 2h2v2h6V2h2v2h2a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2zM5 9v10h14V9zm2 2h4v4H7z"/></svg>`;

function dayLabel(day, today, locale, t) {
  if (day === today) return t.today;
  if (day === shiftDay(today, -1)) return t.yesterday;
  const sameYear = day.slice(0, 4) === today.slice(0, 4);
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone: "UTC",
  }).format(new Date(day));
}

// A food's nutrients for `grams`; missing optional values stay null.
function scaled(food, grams) {
  return Object.fromEntries(NUTRIENTS.map((n) => [n, food[n] == null ? null : (food[n] * grams) / 100]));
}

const optionList = (values, labels, selected) =>
  values.map((v) => `<option value="${esc(v)}"${v === selected ? " selected" : ""}>${esc(labels[v] ?? v)}</option>`).join("");

// The summary and meals of one day, from metron/day. `states`, Home
// Assistant's, names the sensor the day's activity came from, and `person`
// is the name of whose day it is.
function diaryBodyHTML(data, t, locale, states = {}, person = "") {
  const meals = MEALS.map((meal) => mealHTML(meal, data.entries.filter((e) => e.meal === meal), t, locale));
  const line = data.activity ? activityLine(data.activity, states, person, locale, t) : "";
  return diarySummaryHTML(totals(data.entries), data.goals, t, locale, data.activity, line) + meals.join("");
}

// The day's totals `sums`, against its `goals` if it has any. On a day with
// `activity`, metron/day's, the goal splits into the goal without activity
// and what activity added, and `line` goes under the sum.
function diarySummaryHTML(sums, goals, t, locale, activity = null, line = "") {
  if (!goals) {
    return `<div class="summary num"><div></div><span></span><div><b>${number(sums.kcal, locale)}</b><small>${esc(t.food)}</small></div></div>`;
  }
  const left = goals.kcal - sums.kcal;
  // Rounded before the goal is split, so that the sum adds up as shown.
  const added = activity && Math.round(activity.added);
  const goal = activity
    ? `<div><b>${number(goals.kcal - added, locale)}</b><small>${esc(t.goal)}</small></div><span class="op">+</span>
        <div><b>${number(added, locale)}</b><small>${esc(t.activity)}</small></div>`
    : `<div><b>${number(goals.kcal, locale)}</b><small>${esc(t.goal)}</small></div>`;
  return `<div class="summary num${activity ? " withactivity" : ""}">
        ${goal}<span class="op">−</span>
        <div><b>${number(sums.kcal, locale)}</b><small>${esc(t.food)}</small></div><span class="op">=</span>
        <div class="${left < 0 ? "over" : "left"}"><b>${number(Math.abs(left), locale)}</b><small>${esc(left < 0 ? t.over : t.remaining)}</small></div>
      </div>${activity ? `<div class="activity">${esc(line)}</div>` : ""}
      <div class="macros num">${MACROS.map((m) => {
        const share = goals[m] > 0 ? sums[m] / goals[m] : 0;
        return `<div class="macro ${m}${share > 1 ? " over" : ""}"><small>${esc(t[m])}</small>
          <div class="bar"><i style="width:${Math.min(share, 1) * 100}%"></i></div>
          <span>${number(sums[m], locale)} / ${number(goals[m], locale)} g</span></div>`;
      }).join("")}</div>`;
}

// What explains the Activity in the diary's sum, from metron/day's
// `activity`: what was measured or logged, how much of it counts, and how
// much of that the activity level already allows for. Today's status says
// when there is nothing to count yet, or the sensor is unavailable or gone.
// The sensor is named as sensorName says; `person` is the name of whose day
// it is.
function activityLine(activity, states, person, locale, t) {
  const { source, status, measured, share, cap, counted, allowed, added } = activity;
  const logged = source === "action";
  const sensor = sensorName(activity, states);
  if (status === "waiting") return logged ? t.activity_logged_waiting : fill(t.activity_waiting, { sensor });
  if (status === "missing" && measured == null) return fill(t.activity_missing, { sensor, person });
  const leads = { missing: t.activity_missing_held, unavailable: t.activity_unavailable };
  const lead = logged ? t.activity_logged : (leads[status] ?? t.activity_measured);
  // Past days have no status, so whether the cap applied comes from the figures.
  const capped = (measured * share) / 100 > cap;
  const sentences = [
    fill(lead, { sensor, person, measured: number(measured, locale) }),
    fill(capped ? t.activity_capped : t.activity_counts, { share: percent(share, locale), counted: number(counted, locale), cap: number(cap, locale) }),
    allowed === 0 ? t.activity_all : fill(added > 0 ? t.activity_allowed : t.activity_level, { allowed: number(allowed, locale) }),
  ];
  // Chinese runs sentences together; the other languages space them.
  return sentences.join(locale.split("-")[0].toLowerCase() === "zh" ? "" : " ");
}

// The name the activity line gives the sensor `activity` came from: its name
// in `states`, Home Assistant's, else its entity ID, which is all a missing
// sensor has left.
const sensorName = (activity, states) => (activity.status !== "missing" && states[activity.source]?.attributes.friendly_name) || activity.source;

// One meal's `entries`, with buttons to add to it, copy into it, and save
// it as a meal when it has any.
function mealHTML(meal, entries, t, locale) {
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
        ${entries.length ? `<button class="text" data-action="save-as-meal" data-meal="${meal}">${esc(t.save_as_meal)}</button>` : ""}
      </div></div>`;
}

// What the Saved tab of add panel `p` finds: the meals and saved foods
// matching its query, or, before typing, the first three meals A to Z and
// recent foods. Once a meal is chosen, only that meal.
function resultsHTML(p, locale, t, people = []) {
  if (p.chosen) return mealRowHTML(p.chosen, people, locale, t, "choose-meal", true);
  const query = p.query.trim();
  const meals = (p.meals ?? []).filter((m) => nameMatches(m.name, query));
  const shown = query || p.allMeals ? meals : meals.slice(0, 3);
  const mealsHTML = shown.length
    ? `<div class="sub">${esc(t.title_meals)}</div>${shown.map((m) => mealRowHTML(m, people, locale, t, "choose-meal")).join("")}` +
      (shown.length < meals.length ? `<button class="text allmeals" data-action="all-meals">${esc(fill(t.all_meals, { count: meals.length }))}</button>` : "")
    : "";
  const foods = p.results ?? [];
  if (!foods.length) {
    if (query && meals.length) return mealsHTML;
    const empty = p.results === undefined ? t.loading : query ? fill(t.no_results, { query }) : t.no_recent;
    return `${mealsHTML}<div class="muted">${esc(empty)}</div>`;
  }
  return (
    mealsHTML +
    `<div class="sub">${esc(query ? t.results : t.recent)}</div>` +
    foods
      .map(
        (f) => `<button class="row" data-action="choose" data-id="${f.id}" aria-pressed="${p.food?.id === f.id}">
            <span>${esc(f.name)}</span><small class="num">${esc(fill(t.per_100g_value, { kcal: number(f.kcal, locale) }))}</small></button>`,
      )
      .join("")
  );
}

// How much of add panel `p`'s chosen food to log, and to which meal; empty
// until it has one.
function pickedHTML(p, locale, t) {
  if (!p.food) return "";
  const portions = (p.food.portions ?? [])
    .map((q) => `<button data-action="portion" data-grams="${q.grams}">${esc(q.name)} · ${number(q.grams, locale, 1)} g</button>`)
    .join("");
  return `<div><b>${esc(p.food.name)}</b></div>
      <div class="grid">
        <label>${esc(t.grams)}<input data-action="grams" data-field="grams" ${NUMBER_INPUT} value="${p.grams ?? ""}"></label>
        <label>${esc(t.meal)}<select data-action="meal" data-field="meal">${optionList(MEALS, t, p.meal)}</select></label>
      </div>
      ${portions ? `<div class="chips">${portions}</div>` : ""}
      <div class="preview num"></div>
      <div class="actions"><button class="fill" data-action="add-entry">${esc(fill(t.add_to_meal, { meal: t[p.meal] }))}</button></div>`;
}

function previewHTML(food, grams, locale, t) {
  const values = grams > 0 ? scaled(food, grams) : null;
  return REQUIRED_NUTRIENTS
    .map((n) => `<div><b>${values ? number(values[n], locale, n === "kcal" ? 0 : 1) : "–"}</b><small>${esc(n === "kcal" ? t.kcal : `${t[n]} (g)`)}</small></div>`)
    .join("");
}

// The meal chosen on add panel `p`'s Saved tab: its items to tick, the meal
// to add them to, and their totals.
function chosenMealHTML(p, locale, t, people = []) {
  const meal = p.chosen;
  return `<div><b>${esc(meal.name)}</b>${ownerPillHTML(meal.owner, people, t)}</div>
      ${tickListHTML(meal.items, p.ticks, locale, t)}
      <div class="grid"><label>${esc(t.meal)}<select data-action="meal" data-field="meal">${optionList(MEALS, t, p.meal)}</select></label></div>
      <div class="preview num">${totalsHTML(ticked(meal.items, p.ticks), locale, t)}</div>
      <div class="actions"><button class="fill" data-action="log-meal"${p.ticks.some(Boolean) ? "" : " disabled"}>${esc(fill(t.add_to_meal, { meal: t[p.meal] }))}</button></div>`;
}

// Save as meal: a name, the meal's entries to tick, their totals, and
// whether everyone shares it.
function saveMealPanelHTML(p, locale, t) {
  return `<div class="mealhead"><span>${esc(fill(t.save_meal_title, { meal: t[p.meal] }))}</span></div>
    <label>${esc(t.name)}<input data-action="meal-name" data-field="meal-name" value="${esc(p.name)}" enterkeyhint="done"></label>
    ${tickListHTML(p.entries, p.ticks, locale, t)}
    <div class="preview num">${totalsHTML(ticked(p.entries, p.ticks), locale, t)}</div>
    <label class="check"><input type="checkbox" data-action="share"${p.share ? " checked" : ""}><span>${esc(t.share_everyone)}</span></label>
    <div class="actions">${cancelButtonHTML(t)}<button class="fill" data-action="save-meal"${p.ticks.some(Boolean) ? "" : " disabled"}>${esc(t.save_meal)}</button></div>`;
}

// Choose `food` in add panel `p`, at its first portion, else 100 g.
function chooseFood(p, food) {
  p.food = food;
  p.grams = food.portions?.[0]?.grams ?? 100;
}

// Show a saved food chosen on add panel `p`'s Saved tab, as its only
// result, with no note, warning or error, and no new food left to save.
function showSavedFood(p, food) {
  Object.assign(p, {
    tab: "search",
    query: food.name,
    results: [food],
    chosen: null,
    newFood: null,
    review: false,
    note: null,
    warning: null,
    error: null,
    retry: null,
    taken: null,
  });
  chooseFood(p, food);
}

// The add panel: its head with Scan, where the device can scan, and Cancel;
// the camera, when scanning in the browser; a lookup that is running; then
// the Saved, Quick add and New food tabs.
function addPanelHTML(p, t, scan = false, locale = "en") {
  const tabs = ["search", "quick", "new"]
    .map((tab) => `<button data-action="tab" data-tab="${tab}" role="tab" aria-selected="${p.tab === tab}">${esc(t[`tab_${tab}`])}</button>`)
    .join("");
  const cancel = cancelButtonHTML(t);
  let content;
  if (p.tab === "search") {
    content = `<input type="search" data-action="query" value="${esc(p.query)}" placeholder="${esc(t.search_saved)}" aria-label="${esc(t.search_saved)}" enterkeyhint="search">
      <div class="results"></div><div class="find"></div><div class="picked"></div>`;
  } else if (p.tab === "quick") {
    const typed = p.quick ?? {};
    const n = (key, label) => `<label>${esc(label)}<input data-field="${key}" ${NUMBER_INPUT} value="${esc(typed[key] ?? "")}"></label>`;
    content = `<div class="grid"><label>${esc(t.name)}<input data-field="name" value="${esc(typed.name ?? "")}"></label>${n("kcal", t.kcal)}</div>
      <div class="grid">${MACROS.map((m) => n(m, `${t[m]} (g, ${t.optional})`)).join("")}</div>
      <label>${esc(t.meal)}<select data-field="meal">${optionList(MEALS, t, typed.meal ?? p.meal)}</select></label>
      <div class="actions">${cancel}<button class="fill" data-action="quick-add">${esc(t.add)}</button></div>`;
  } else {
    const body = p.review ? reviewHTML(p.newFood, locale, t) : foodFormHTML(p.newFood ?? {}, t, false, false);
    content = `${offFinderHTML(p.offQuery, t)}${body}
      <div class="actions">${cancel}<button class="fill" data-action="save-new-food">${esc(t.save_and_choose)}</button></div>`;
  }
  const scanButton = scan ? `<button class="text" data-action="scan">${esc(t.scan)}</button>` : "";
  return `<div class="mealhead"><span>${esc(fill(t.add_to_meal, { meal: t[p.meal] }))}</span><span class="headactions">${scanButton}${cancel}</span></div>
    <div class="scanner" hidden></div>${p.lookup ? lookingUpHTML(p.lookup.code, t) : ""}
    <div class="tabs" role="tablist">${tabs}</div>${content}`;
}

// What an entry's amount is edited in: grams if it was logged by weight,
// else kcal, as a quick add is.
const amountField = (entry) => (entry.grams != null ? "grams" : "kcal");

function editPanelHTML(p, locale, t) {
  const e = p.entry;
  const field = amountField(e);
  const amount = `<label>${esc(t[field])}<input data-field="${field}" ${NUMBER_INPUT} value="${esc(p.amount ?? e[field])}"></label>`;
  const buttons = p.confirming
    ? `<span class="error">${esc(fill(t.really_delete, { name: e.name }))}</span>
       ${cancelButtonHTML(t)}<button class="danger" data-action="really-delete">${esc(t.yes_delete)}</button>`
    : `<button class="text" data-action="delete-entry">${esc(t.delete)}</button>${cancelButtonHTML(t)}
       <button class="fill" data-action="save-edit">${esc(t.save)}</button>`;
  return `<div class="mealhead"><span>${esc(t.edit_entry)}: ${esc(e.name)}</span><span class="sub num">${number(e.kcal, locale)} ${esc(t.kcal)}</span></div>
    <div class="grid">${amount}<label>${esc(t.meal)}<select data-field="meal">${optionList(MEALS, t, p.meal ?? e.meal)}</select></label></div>
    <div class="actions">${buttons}</div>`;
}

function copyPanelHTML(p, today, t) {
  return `<div class="mealhead"><span>${esc(fill(t.copy_title, { meal: t[p.meal] }))}</span></div>
    <div class="grid">
      <label>${esc(t.copy_from_day)}<input data-field="from_day" type="date" value="${p.fromDay}" max="${today}"></label>
      <label>${esc(t.copy_from_meal)}<select data-field="from_meal">${optionList(MEALS, t, p.fromMeal)}</select></label>
    </div>
    <div class="actions">${cancelButtonHTML(t)}<button class="fill" data-action="do-copy">${esc(t.copy)}</button></div>`;
}
