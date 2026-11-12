// Saved meals and who saved what, for the food diary, saved foods and saved
// meals cards. A meal, from metron/meals, is {id, owner, name,
// version, items}: owner is a person's id, or null for everyone, and each
// item is {id, food_id, name, grams, nutrients...}, its food's values now
// for a saved food, else fixed values, from a quick add.

// The styles of what follows. Every card with a food form has them.
const SAVED_MEAL_STYLE = `
  .pill { display: inline-block; font-size: var(--ha-font-size-xs, 0.75rem); font-weight: var(--ha-font-weight-medium, 500); line-height: 1.7;
    padding: 0 7px; margin-left: 6px; border-radius: 9px; background: var(--secondary-background-color); color: var(--secondary-text-color);
    vertical-align: 1px; white-space: nowrap; }
  .pill.everyone { background: color-mix(in srgb, var(--primary-color) 14%, transparent); color: var(--primary-color); }
  .mealrow > span:first-child { min-width: 0; }
  .mealrow .foods-in { display: block; color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .items { display: flex; flex-direction: column; }
  label.item, label.check { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px;
    padding: 6px 4px; font-size: inherit; color: var(--primary-text-color); cursor: pointer; }
  label.check { grid-template-columns: auto 1fr; }
  .item input, .check input { width: 18px; height: 18px; padding: 0; margin: 0; accent-color: var(--primary-color); }
  .item .amount { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 0.875rem); margin-left: 6px; }
  .item:has(input:not(:checked)) > span { color: var(--secondary-text-color); }
  .preview { display: grid; grid-template-columns: repeat(4, 1fr); text-align: center; gap: 4px;
    background: var(--secondary-background-color); border-radius: 8px; padding: 8px 4px; }
  .preview small { display: block; color: var(--secondary-text-color); font-size: var(--ha-font-size-xs, 0.75rem); }
  .alert { border-left: 3px solid var(--warning-color); background: color-mix(in srgb, var(--warning-color) 14%, transparent);
    padding: 8px 10px; border-radius: 6px; }
`;

// The name of the person with `id`, or null.
const personName = (people, id) => people?.find((p) => p.id === id)?.name ?? null;

// A meal's owner as a pill: Everyone, or the person's name.
function ownerPillHTML(owner, people, t) {
  if (owner == null) return `<span class="pill everyone">${esc(t.everyone)}</span>`;
  const name = personName(people, owner);
  return name ? `<span class="pill">${esc(name)}</span>` : "";
}

// Who saved a food, as a pill, when that is known.
function savedByPillHTML(food, people) {
  const name = personName(people, food.saved_by);
  return name ? `<span class="pill">${esc(name)}</span>` : "";
}

// `names` as one phrase, joined as `locale` joins a list: "A, B and C".
const listText = (names, locale) => new Intl.ListFormat(locale, { type: "conjunction" }).format(names);

// Whether `name` contains `query`, ignoring case.
const nameMatches = (name, query) => name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());

// A meal as a row: its name and owner, its foods, its kcal. Tapping it
// runs `action` with the meal's id.
function mealRowHTML(meal, people, locale, t, action, pressed = false) {
  return `<button class="row mealrow" data-action="${action}" data-id="${meal.id}"${pressed ? ' aria-pressed="true"' : ""}>
    <span><span class="mname">${esc(meal.name)}</span>${ownerPillHTML(meal.owner, people, t)}<small class="foods-in">${esc(meal.items.map((i) => i.name).join(", "))}</small></span>
    <small class="num">${number(totals(meal.items).kcal, locale)} ${esc(t.kcal)}</small></button>`;
}

// What follows an item's or entry's name: its grams, and "Quick add" when it
// has no saved food.
function amountTagHTML(item, locale, t) {
  const grams = item.grams != null ? `${number(item.grams, locale, 1)} g` : "";
  const text = item.food_id == null ? [grams, t.tab_quick].filter(Boolean).join(" · ") : grams;
  return text ? `<span class="amount num">${esc(text)}</span>` : "";
}

// Items or entries, each with a box to tick, its amount and its kcal.
function tickListHTML(items, ticks, locale, t) {
  return `<div class="items">${items
    .map(
      (item, i) => `<label class="item"><input type="checkbox" data-action="tick" data-index="${i}"${ticks[i] ? " checked" : ""}>
      <span>${esc(item.name)}${amountTagHTML(item, locale, t)}</span><span class="num">${number(item.kcal ?? 0, locale)}</span></label>`,
    )
    .join("")}</div>`;
}

// The kcal, protein, carbs and fat of `items` together, for a .preview box.
function totalsHTML(items, locale, t) {
  const sums = totals(items);
  return REQUIRED_NUTRIENTS.map(
    (n) => `<div><b>${number(sums[n], locale, n === "kcal" ? 0 : 1)}</b><small>${esc(n === "kcal" ? t.kcal : `${t[n]} (g)`)}</small></div>`,
  ).join("");
}

// The ticked ones of `items`.
const ticked = (items, ticks) => items.filter((_, i) => ticks[i]);

// The message for a meal/add or meal/update refused with meal_exists: whose
// meal has `name` already.
function mealExistsText(err, name, people, t) {
  const owner = err?.translation_placeholders?.owner;
  if (!owner) return fill(t.meal_exists_everyone, { name });
  return fill(t.meal_exists_person, { person: personName(people, owner) ?? owner, name });
}

// The warning for a food that food/add found saved already: by barcode, or
// by name. `taken` is the error's details: {food_id, name, saved_by}.
function takenText(code, taken, people, t) {
  const person = personName(people, taken.saved_by);
  if (code === "barcode_taken") return person ? fill(t.already_saved_by, { person, name: taken.name }) : fill(t.already_saved_as, { name: taken.name });
  return person ? fill(t.name_saved_by, { person, name: taken.name }) : fill(t.name_saved, { name: taken.name });
}

// A food's short check, after Open Food Facts filled it in: its name and
// barcode, its kcal, protein, carbs and fat per 100 g, and its portions,
// with Edit values to open the whole form.
function reviewHTML(food, locale, t) {
  const portions = (food.portions ?? []).map((q) => `<span class="chip">${esc(q.name)} · ${number(q.grams, locale, 1)} g</span>`).join("");
  return `<div class="review">
    <div class="reviewhead"><span><b>${esc(food.name)}</b>${food.barcode ? `<small class="num">${esc(food.barcode)}</small>` : ""}</span>
      <button class="text" data-action="edit-values">${esc(t.edit_values)}</button></div>
    <div class="sub">${esc(t.per_100g)}</div><div class="preview num">${totalsHTML([food], locale, t)}</div>
    ${portions ? `<div class="chips">${portions}</div>` : ""}</div>`;
}

// Whether a food filled in from Open Food Facts can be saved from its short
// check: it has a name, and its kcal, protein, carbs and fat.
const reviewable = (food) => Boolean(food.name) && REQUIRED_NUTRIENTS.every((n) => food[n] != null && food[n] >= 0);

// The line that shows while barcode `code` is being looked up, with Cancel.
const lookingUpHTML = (code, t) =>
  `<div class="lookup"><span class="spinner"></span><span>${esc(fill(t.looking_up, { code }))}</span><button class="text" data-action="cancel-lookup">${esc(t.cancel)}</button></div>`;
