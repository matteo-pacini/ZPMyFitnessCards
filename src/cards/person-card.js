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

// The loading of a card that shows one person, as a subclass of `Base`: the
// person its config names, or the logged-in user's, and that person's data
// from the card's `_fetch`, drawn with `_renderBody`. Its title is its
// config's, else the string its static `titleKey` names. Once midnight
// passes, it calls `_newDay`, which fetches again. Each fetch reads the
// person again too, so the card follows a change to their details.
const ShowsPerson = (Base) =>
  class extends Base {
    set hass(hass) {
      super.hass = hass;
      // Home Assistant passes a new hass at least as often as its states
      // change, and Metron's own sensors start the new day at midnight.
      if (this._data && this._fetchedOn !== this._today) this._newDay();
    }

    async _load() {
      this._people = await this._call({ type: "metron/people" });
      this._person = findPerson(this._people, this._config, this._hass);
      this._fetchedOn = this._today;
      this._data = this._person ? await this._fetch() : null;
    }

    _newDay() {
      this._refresh();
    }

    async _refresh() {
      this._fetchedOn = this._today;
      try {
        const [people, data] = await Promise.all([this._call({ type: "metron/people" }), this._fetch()]);
        const person = findPerson(people, this._config, this._hass);
        // Someone else, or no one, as after a rename when the config names
        // the person: `data` is not theirs, so load afresh.
        if (person?.id !== this._person.id) return this._start();
        const same = JSON.stringify(person) === JSON.stringify(this._person);
        this._people = people;
        this._person = person;
        this._data = data;
        // The whole card only when it must be: the diary draws its open panel
        // again with it, which drops the focus and what is typed in the panel.
        if (same) this._renderBody();
        else this._render();
      } catch {
        this._start();
      }
    }

    // A change to the person `event` names: fetch again when they are the
    // card's. A card with no one to show looks for its person again, since
    // they may have just been added, or renamed to the name its config has.
    _personChanged(event) {
      if (!this._person) this._start();
      else if (event.person === this._person.id) this._refresh();
    }

    get _titleHTML() {
      return `<div class="title">${esc(this._config.title || this._t[this.constructor.titleKey])}</div>`;
    }

    // While there is no person to show, draw why: loading, a failure, or
    // none found. Returns whether it drew.
    _renderNoPerson() {
      if (this._person) return false;
      const t = this._t;
      let message = t.loading;
      if (this._failure) message = fill(t.error_failed, { message: this._failure.message ?? "" });
      else if (this._data === null) message = this._config.person ? fill(t.unknown_person, { name: this._config.person }) : t.no_person;
      this._card.innerHTML = `${this._titleHTML}<div class="${message === t.loading ? "muted" : "error"}">${esc(message)}</div>`;
      return true;
    }
  };

// Base for the cards that show one person.
class PersonCard extends ShowsPerson(FitnessCard) {
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

  _changed(event) {
    if (event.person !== null) this._personChanged(event);
  }

  _render() {
    if (!this._card || this._renderNoPerson()) return;
    this._card.innerHTML = `<div class="head"><div>${this._titleHTML}<div class="sub person">${esc(this._person.name)}</div></div>
      ${rangeButtons(this.constructor.ranges, this._range, this._t)}</div><div class="body"></div>`;
    this._renderBody();
  }
}
