// The first day a range shows, ending today. "all" starts at `firstDay`,
// the first day with data, or 30 days back when there is none before today.
function rangeStart(range, today, firstDay) {
  if (range === "all") return firstDay && firstDay < today ? firstDay : shiftDay(today, -29);
  return shiftDay(today, -(Number(range) - 1));
}

const rangeButtons = (ranges, selected, t) =>
  !ranges.length ? "" : `<div class="ranges" role="group">${ranges
    .map((r) => `<button data-action="range" data-range="${r}" aria-pressed="${String(r) === String(selected)}">${esc(t[`range_${r}`])}</button>`)
    .join("")}</div>`;

// Base for the cards that show one person.
class PersonCard extends FitnessCard {
  static options = ["person", "title", "locale"];
  // The style of rangeButtons. A card's own style adds to it.
  static style = `
    .ranges { display: flex; gap: 4px; flex-wrap: wrap; }
    .ranges button { border: 1px solid var(--divider-color); border-radius: 16px; padding: 4px 10px; font-size: var(--ha-font-size-s, 0.875rem); }
    .ranges button[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color); border-color: var(--primary-color); }
  `;

  set hass(hass) {
    const unit = this._hass && weightUnit(this._hass);
    super.hass = hass;
    // Home Assistant's unit system changed: show weights in the new unit.
    if (unit && unit !== weightUnit(hass)) this._render();
  }

  async _load() {
    const people = await this._call({ type: "fork_and_scale/people" });
    this._person = findPerson(people, this._config, this._hass);
    this._data = this._person ? await this._fetch() : null;
  }

  async _refresh() {
    try {
      this._data = await this._fetch();
      this._renderBody();
    } catch {
      this._start();
    }
  }

  _changed(event) {
    if (this._person && event.person === this._person.id) this._refresh();
  }

  _render() {
    if (!this._card) return;
    const t = this._t;
    const title = `<div class="title">${esc(this._config.title || t[this.constructor.titleKey])}</div>`;
    if (!this._person) {
      let message = t.loading;
      if (this._failure) message = fill(t.error_failed, { message: this._failure.message ?? "" });
      else if (this._data === null) message = this._config.person ? fill(t.unknown_person, { name: this._config.person }) : t.no_person;
      this._card.innerHTML = `${title}<div class="${message === t.loading ? "muted" : "error"}">${esc(message)}</div>`;
      return;
    }
    this._card.innerHTML = `<div class="head"><div>${title}<div class="sub person">${esc(this._person.name)}</div></div>
      ${rangeButtons(this.constructor.ranges, this._range, t)}</div><div class="body"></div>`;
    this._renderBody();
  }
}
