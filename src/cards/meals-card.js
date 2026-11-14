// The household's saved meals: find, add, change and delete them. With a
// person in its config, it shows everyone's meals and that person's own;
// without, every meal.
class MealsCard extends FoodCard {
  static style = `${super.style}
    .list { display: flex; flex-direction: column; max-height: 420px; overflow-y: auto; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 8px; width: 100%; text-align: left; padding: 8px 4px; border-top: 1px solid var(--divider-color); border-radius: 0; }
    .mealitems { display: flex; flex-direction: column; gap: 6px; }
    .mealitem { display: grid; grid-template-columns: minmax(0, 1fr) 96px 3em auto; gap: 8px; align-items: center; }
    .mealitem .qty { display: flex; align-items: center; gap: 4px; }
    .mealitem .qty input { width: 100%; }
    .mealitem .qty small, .mealitem .kcal { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); }
    .mealitem .kcal { text-align: right; }
    .fixeditem { display: flex; flex-direction: column; gap: 6px; padding: 6px 0;
      border-top: 1px dashed var(--divider-color); border-bottom: 1px dashed var(--divider-color); }
    .fixedtop { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; }
    .fixedtop .pill { margin-left: 0; }
    .fixedvals { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
    .fixedvals label { font-size: var(--ha-font-size-xs, 0.75rem); }
    .addfood { display: flex; flex-direction: column; gap: 8px; }
    .addfood .results { display: flex; flex-direction: column; max-height: 200px; overflow-y: auto; }
    .addfood .row { border-top: 0; padding: 6px 4px; }
  `;

  static options = ["person", "title", "locale"];
  // Without a person this card shows every meal, so its editor says so.
  static editorStrings = { editor_person_linked: "editor_person_all", editor_person_helper: "editor_meals_person_helper" };

  getCardSize() {
    return 6;
  }

  async _load() {
    this._query ??= "";
    this._people = await this._call({ type: "metron/people" });
    this._person = this._config.person ? findPerson(this._people, this._config, this._hass) : null;
    if (this._config.person && !this._person) {
      this._meals = null;
      return;
    }
    this._meals = await this._call({ type: "metron/meals", ...(this._person && { person: this._person.id }) });
  }

  // Meals change with foods, whose names and values their items show.
  _changed(event) {
    if (event.person === null) this._refresh();
  }

  async _refresh() {
    const listed = Boolean(this._meals);
    try {
      await this._load();
      // The person the config names found at last, or gone: the card goes
      // from its message to its list, or back, so all of it is drawn.
      if (Boolean(this._meals) === listed) this._renderList();
      else this._render();
    } catch {
      this._start();
    }
  }

  _render() {
    if (!this._card) return;
    const t = this._t;
    const title = `<div class="title">${esc(this._config.title || t.title_meals)}</div>`;
    if (!this._meals) {
      let message = t.loading;
      if (this._failure) message = fill(t.error_failed, { message: this._failure.message ?? "" });
      else if (this._meals === null) message = fill(t.unknown_person, { name: this._config.person });
      this._card.innerHTML = `${title}<div class="${message === t.loading ? "muted" : "error"}">${esc(message)}</div>`;
      return;
    }
    this._card.innerHTML = `<div class="head">${title}<button class="fill" data-action="new">+ ${esc(t.add_meal)}</button></div>
      <input type="search" data-action="query" value="${esc(this._query)}" placeholder="${esc(t.search_meals)}" aria-label="${esc(t.search_meals)}">
      <div class="panel" hidden></div><div class="list"></div>`;
    this._renderList();
    this._renderPanel();
  }

  _renderList() {
    const list = this._card?.querySelector(".list");
    if (list && this._meals) list.innerHTML = mealsListHTML(this._meals, this._query, this._people, this._locale, this._t);
  }

  _renderPanel() {
    const panel = this._card?.querySelector(".panel");
    if (!panel) return;
    const p = this._panel;
    panel.hidden = !p;
    panel.innerHTML = p ? mealEditorHTML(p, this._people, this._locale, this._t) : "";
  }

  // The totals, and each saved food's kcal, which follow the grams typed.
  // Only these redraw, so the box being typed in keeps focus.
  _renderTotals() {
    const p = this._panel;
    this._card.querySelector(".panel .preview").innerHTML = totalsHTML(p.items, this._locale, this._t);
    this._card.querySelectorAll(".panel .mealitem .kcal").forEach((cell) => {
      cell.textContent = number(p.items[Number(cell.dataset.index)].kcal ?? 0, this._locale);
    });
  }

  _openEditor(meal) {
    const owner = meal ? meal.owner : (this._person?.id ?? null);
    this._panel = {
      meal,
      name: meal?.name ?? "",
      owner,
      items: (meal?.items ?? []).map(editableItem),
      addQuery: "",
      addResults: null,
    };
    this._renderPanel();
    this._card.querySelector('.panel [data-field="meal-name"]')?.focus?.();
  }

  _closeEditor() {
    this._panel = null;
    this._renderPanel();
  }

  async _searchFoods() {
    const p = this._panel;
    const query = p.addQuery.trim();
    if (!query) {
      p.addResults = null;
      this._renderAddResults();
      return;
    }
    try {
      const found = await this._call({ type: "metron/food/search", query });
      if (this._panel === p && p.addQuery.trim() === query) {
        p.addResults = found;
        this._renderAddResults();
      }
    } catch (err) {
      this._showError(err);
    }
  }

  _renderAddResults() {
    const box = this._card.querySelector(".panel .addfood .results");
    if (box) box.innerHTML = addFoodResultsHTML(this._panel, this._locale, this._t);
  }

  // Send `message`, which saves or deletes the open meal, then close the
  // editor. A change someone else made first, or a name another meal has,
  // is refused, and the editor says so.
  async _write(message) {
    const p = this._panel;
    const t = this._t;
    try {
      await this._call(message);
      if (this._panel === p) this._closeEditor();
      await this._refresh();
    } catch (err) {
      if (this._panel !== p) return;
      if (err?.code === "meal_exists") p.error = mealExistsText(err, p.name.trim(), this._people, t);
      else if (err?.code === "meal_changed") p.error = fill(t.meal_changed, { name: p.meal.name });
      else return this._showError(err);
      p.confirming = false;
      this._renderPanel();
      this._revealButtons();
    }
  }

  static actions = {
    "click:new"() {
      this._openEditor(null);
    },
    "click:edit-meal"(el) {
      this._openEditor(this._meals.find((m) => String(m.id) === el.dataset.id));
    },
    "click:close"() {
      this._closeEditor();
    },
    "input:query"(el) {
      this._query = el.value;
      this._renderList();
    },
    "input:meal-name"(el) {
      this._panel.name = el.value;
    },
    "keydown:meal-name"(el, event) {
      if (event.key === "Enter") this.constructor.actions["click:save-meal"].call(this);
    },
    "change:owner"(el) {
      this._panel.owner = el.value || null;
    },
    "input:item-grams"(el) {
      const item = this._panel.items[Number(el.dataset.index)];
      setGrams(item, numberValue(el));
      this._renderTotals();
    },
    "input:fixed"(el) {
      const item = this._panel.items[Number(el.dataset.index)];
      const key = el.dataset.key;
      item[key] = key === "name" ? el.value : numberValue(el);
      this._renderTotals();
    },
    "click:remove-item"(el) {
      this._panel.items.splice(Number(el.dataset.index), 1);
      this._renderPanel();
    },
    "input:add-food"(el) {
      this._panel.addQuery = el.value;
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => this._searchFoods(), SEARCH_DELAY_MS);
    },
    "click:add-item"(el) {
      const p = this._panel;
      const food = p.addResults.find((f) => String(f.id) === el.dataset.id);
      p.items.push(foodItem(food));
      Object.assign(p, { addQuery: "", addResults: null });
      this._renderPanel();
      const fields = this._card.querySelectorAll('.panel [data-action="item-grams"]');
      fields[fields.length - 1]?.focus?.();
    },
    async "click:save-meal"() {
      const p = this._panel;
      const name = p.name.trim();
      if (!name) return this._showError(null, "error_meal_name");
      const items = p.items.map(itemToSave);
      if (!items.length || items.includes(null)) return this._showError(null, "error_meal_items");
      const fields = { name, owner: p.owner, items };
      await this._write(
        p.meal
          ? { type: "metron/meal/update", meal_id: p.meal.id, version: p.meal.version, ...fields }
          : { type: "metron/meal/add", ...fields },
      );
    },
    "click:delete-meal"() {
      this._panel.confirming = true;
      this._renderPanel();
      this._revealButtons();
    },
    async "click:really-delete"() {
      const meal = this._panel.meal;
      await this._write({ type: "metron/meal/delete", meal_id: meal.id, version: meal.version });
    },
  };
}

// An item of a meal as the editor keeps it: a saved food's keeps its values
// per 100 g, so they can follow new grams.
function editableItem(item) {
  if (item.food_id == null) return { ...item };
  const per100g = Object.fromEntries(NUTRIENTS.map((n) => [n, item[n] == null ? null : (item[n] * 100) / item.grams]));
  return { ...item, per100g };
}

// A saved food as a new item, at its first portion, else 100 g.
function foodItem(food) {
  const per100g = Object.fromEntries(NUTRIENTS.map((n) => [n, food[n]]));
  const item = { food_id: food.id, name: food.name, per100g };
  setGrams(item, food.portions?.[0]?.grams ?? 100);
  return item;
}

// Set a saved food's item to `grams`, and its values to match.
function setGrams(item, grams) {
  item.grams = grams;
  for (const n of NUTRIENTS) item[n] = grams > 0 && item.per100g[n] != null ? (item.per100g[n] * grams) / 100 : null;
}

// An item as metron/meal/add and meal/update take it, or null if it
// is not filled in right: a saved food needs grams above 0, fixed values a
// name and kcal.
function itemToSave(item) {
  if (item.food_id != null) return item.grams > 0 ? { food_id: item.food_id, grams: item.grams } : null;
  if (!item.name?.trim() || item.kcal == null || item.kcal < 0) return null;
  if (MACROS.some((m) => item[m] != null && item[m] < 0)) return null;
  return { name: item.name.trim(), grams: item.grams ?? null, ...Object.fromEntries(NUTRIENTS.map((n) => [n, item[n] ?? null])) };
}

// Meals as rows, A to Z, those whose names contain `query`.
function mealsListHTML(meals, query, people, locale, t) {
  const text = query.trim();
  const shown = meals.filter((m) => nameMatches(m.name, text)).sort((a, b) => a.name.localeCompare(b.name, locale));
  if (!shown.length) return `<div class="muted">${esc(text ? fill(t.no_meals, { query: text }) : t.meals_empty)}</div>`;
  return shown.map((m) => mealRowHTML(m, people, locale, t, "edit-meal")).join("");
}

// One item in the editor. A saved food's takes grams; fixed values, from a
// quick add, take a name, kcal, protein, carbs and fat, tagged Quick add.
function itemEditorHTML(item, i, locale, t) {
  const remove = `<button class="text" data-action="remove-item" data-index="${i}">${esc(t.remove)}</button>`;
  if (item.food_id != null) {
    return `<div class="mealitem"><span>${esc(item.name)}</span>
      <span class="qty"><input data-action="item-grams" data-index="${i}" ${NUMBER_INPUT} value="${item.grams ?? ""}" aria-label="${esc(t.grams)}"><small>g</small></span>
      <span class="num kcal" data-index="${i}">${number(item.kcal ?? 0, locale)}</span>${remove}</div>`;
  }
  const value = (key) => {
    const label = key === "kcal" ? t.kcal : `${t[key]} (g)`;
    return `<label>${esc(label)}<input data-action="fixed" data-key="${key}" data-index="${i}" ${NUMBER_INPUT} value="${item[key] ?? ""}"></label>`;
  };
  return `<div class="fixeditem"><div class="fixedtop">
      <input data-action="fixed" data-key="name" data-index="${i}" value="${esc(item.name ?? "")}" aria-label="${esc(t.name)}">
      <span class="pill">${esc(t.tab_quick)}</span>${remove}</div>
    <div class="fixedvals">${REQUIRED_NUTRIENTS.map(value).join("")}</div></div>`;
}

function addFoodResultsHTML(p, locale, t) {
  if (!p.addResults) return "";
  if (!p.addResults.length) return `<div class="muted">${esc(fill(t.no_results, { query: p.addQuery.trim() }))}</div>`;
  return p.addResults
    .map(
      (f) => `<button class="row" data-action="add-item" data-id="${f.id}"><span>${esc(f.name)}</span>
      <small class="num">${esc(fill(t.per_100g_value, { kcal: number(f.kcal, locale) }))}</small></button>`,
    )
    .join("");
}

// The editor of meal `p.meal`, or of a new one: its name and who it is for,
// its items, a search to add saved foods, and its totals.
function mealEditorHTML(p, people, locale, t) {
  const owners = [["", t.everyone], ...people.map((person) => [person.id, person.name])];
  const ownerSelect = owners.map(([v, label]) => `<option value="${esc(v)}"${(p.owner ?? "") === v ? " selected" : ""}>${esc(label)}</option>`).join("");
  const buttons = p.confirming
    ? `<span class="error">${esc(fill(t.really_delete, { name: p.meal.name }))}</span>
       ${cancelButtonHTML(t)}<button class="danger" data-action="really-delete">${esc(t.yes_delete)}</button>`
    : `${p.meal ? `<button class="text" data-action="delete-meal">${esc(t.delete)}</button>` : ""}
       ${cancelButtonHTML(t)}<button class="fill" data-action="save-meal">${esc(t.save_meal)}</button>`;
  return `<div class="title">${esc(p.meal ? p.meal.name : t.add_meal)}</div>
    <div class="grid"><label>${esc(t.name)}<input data-action="meal-name" data-field="meal-name" value="${esc(p.name)}" enterkeyhint="done"></label>
      <label>${esc(t.meal_for)}<select data-action="owner">${ownerSelect}</select></label></div>
    <div class="sub">${esc(t.foods_in_meal)}</div>
    <div class="mealitems">${p.items.map((item, i) => itemEditorHTML(item, i, locale, t)).join("") || `<div class="muted">–</div>`}</div>
    <div class="addfood"><input type="search" data-action="add-food" value="${esc(p.addQuery)}" placeholder="${esc(t.meal_add_food)}" aria-label="${esc(t.meal_add_food)}">
      <div class="results">${addFoodResultsHTML(p, locale, t)}</div></div>
    <div class="sub">${esc(t.total)}</div><div class="preview num">${totalsHTML(p.items, locale, t)}</div>
    ${p.confirming ? `<div class="note">${esc(t.meal_entries_stay)}</div>` : ""}${panelMessagesHTML(p, t)}
    <div class="actions">${buttons}</div>`;
}
