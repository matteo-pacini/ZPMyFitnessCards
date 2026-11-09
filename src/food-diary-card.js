// Food diary card (custom:zp-food-diary-card): one person's day of food.
//
// Config:
//   person  the person's name, as added to the ZPMyFitnessCards integration
//   locale  optional language code; defaults to Home Assistant's language

const STRINGS = {
  en: { title: "Food diary", unknown_person: "No person named {name}. Add them in Settings, Devices & services, ZPMyFitnessCards." },
  de: { title: "Ernährungstagebuch", unknown_person: "Keine Person namens {name}. Füge sie unter Einstellungen, Geräte & Dienste, ZPMyFitnessCards hinzu." },
  es: { title: "Diario de comidas", unknown_person: "No hay ninguna persona llamada {name}. Añádela en Ajustes, Dispositivos y servicios, ZPMyFitnessCards." },
  fr: { title: "Journal alimentaire", unknown_person: "Aucune personne nommée {name}. Ajoutez-la dans Paramètres, Appareils et services, ZPMyFitnessCards." },
  it: { title: "Diario alimentare", unknown_person: "Nessuna persona di nome {name}. Aggiungila in Impostazioni, Dispositivi e servizi, ZPMyFitnessCards." },
  nl: { title: "Voedingsdagboek", unknown_person: "Geen persoon met de naam {name}. Voeg die toe via Instellingen, Apparaten en diensten, ZPMyFitnessCards." },
  pl: { title: "Dziennik żywienia", unknown_person: "Brak osoby o imieniu {name}. Dodaj ją w Ustawienia, Urządzenia oraz usługi, ZPMyFitnessCards." },
  pt: { title: "Diário alimentar", unknown_person: "Não há nenhuma pessoa chamada {name}. Adicione-a em Definições, Dispositivos e serviços, ZPMyFitnessCards." },
  "pt-BR": { unknown_person: "Não há nenhuma pessoa chamada {name}. Adicione-a em Configurações, Dispositivos e serviços, ZPMyFitnessCards." },
  sv: { title: "Matdagbok", unknown_person: "Ingen person som heter {name}. Lägg till personen under Inställningar, Enheter och tjänster, ZPMyFitnessCards." },
  "zh-Hans": { title: "饮食日记", unknown_person: "没有名为 {name} 的人。请在“设置 > 设备与服务 > ZPMyFitnessCards”中添加。" },
};

// The strings for `locale`: the exact language, then its base language
// (pt-BR falls back to pt for keys it does not override, and any Chinese to
// zh-Hans), then English.
function translate(locale) {
  const base = locale.split("-")[0];
  const exact = Object.keys(STRINGS).find((k) => k.toLowerCase() === locale.toLowerCase());
  const zh = base === "zh" ? STRINGS["zh-Hans"] : undefined;
  return { ...STRINGS.en, ...STRINGS[base], ...zh, ...(exact && STRINGS[exact]) };
}

const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const STYLE = `
  ha-card { padding: 16px; }
  .title { font-size: var(--ha-font-size-l, 1.25rem); font-weight: var(--ha-font-weight-medium, 500); }
  .person { color: var(--secondary-text-color); }
  .error { color: var(--error-color); }
`;

class FoodDiaryCard extends HTMLElement {
  setConfig(config) {
    if (!config || typeof config.person !== "string" || !config.person.trim()) {
      throw new Error("Set person: to the name of a person added to ZPMyFitnessCards.");
    }
    this._config = config;
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._loadPeople();
    this._render();
  }

  async _loadPeople() {
    this._people = await this._hass.connection.sendMessagePromise({ type: "zp_my_fitness/people" });
    this._render();
  }

  _render() {
    if (!this._config || !this._hass) return;
    const t = translate(this._config.locale || this._hass.locale?.language || "en");
    const wanted = this._config.person.trim().toLowerCase();
    const person = this._people?.find((p) => p.name.toLowerCase() === wanted);
    let body = "";
    if (person) body = `<div class="person">${esc(person.name)}</div>`;
    else if (this._people) body = `<div class="error">${esc(fill(t.unknown_person, { name: this._config.person }))}</div>`;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="title">${esc(t.title)}</div>${body}</ha-card>`;
  }

  getCardSize() {
    return 2;
  }

  static getStubConfig() {
    return { person: "" };
  }
}

// Home Assistant's frontend replaces window.customElements with its own
// registry as it boots, and only finds cards defined there. The integration
// loads this file alongside the frontend, so wait for the frontend's own
// <home-assistant> element, which it defines once that registry is in place.
customElements.whenDefined("home-assistant").then(() => {
  window.customElements.define("zp-food-diary-card", FoodDiaryCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "zp-food-diary-card",
    name: "Food diary",
    description: "One person's food for the day, from ZPMyFitnessCards",
    documentationURL: "https://github.com/matteo-pacini/ZPMyFitnessCards#food-diary-card",
  });
});
