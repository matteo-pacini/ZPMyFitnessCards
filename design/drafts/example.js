// A small, complete UX draft on design/drafts/kit.js, to start a new draft
// from. Its change, Clear on a meal of the food diary, is made up: it shows
// the kit, not a plan.
//
//   node design/drafts/example.js <out.html>

const kit = require("./kit.js");

async function build(file) {
  const k = await kit.open();
  const { esc, fill, step, t$ } = k;
  const t = k.strings("en", { en: { clear: "Clear", clear_title: "Clear {meal}?", clear_note: "This deletes {count} entries." } });
  const diaryBodyHTML = k.g("diaryBodyHTML");
  const goals = { kcal: 1900, protein: 95, carbs: 238, fat: 63 };
  const entry = (id, name, grams, kcal) => ({ id, meal: "breakfast", food_id: id, name, grams, kcal, protein: 1, carbs: 10, fat: 1 });
  const breakfast = [entry(1, "Porridge oats", 60, 227), entry(2, "Semi-skimmed milk", 200, 98)];

  // Before: the card's real markup. After: the same, plus the proposal.
  const body = (entries, clear) => {
    const html = diaryBodyHTML({ entries, goals }, t, t.lang);
    return clear ? html.replace(/(data-action="copy" data-meal="breakfast">[^<]*<\/button>)/, `$1<button class="text" data-t="clear">${esc(t.clear)}</button>`) : html;
  };
  const card = (entries, { clear = true, panel = "" } = {}) =>
    `<ha-card class="diary"><div class="body">${body(entries, clear)}</div>${panel ? `<div class="panel">${panel}</div>` : ""}</ha-card>`;
  const confirm = () => `<div class="mealhead"><span>${esc(fill(t.clear_title, { meal: t.breakfast }))}</span></div>
    <div class="note">${esc(fill(t.clear_note, { count: breakfast.length }))}</div>
    <div class="actions"><button class="text" data-t="cancel">${esc(t.cancel)}</button><button class="danger" data-t="really-clear">${esc(t.clear)}</button></div>`;

  return k.write(file, {
    title: "Example Draft",
    heading: "Example: Clear a meal",
    intro: "A made-up change, to show what a draft built with the kit looks like.",
    brief: `<div class="brief"><div><h4>Why</h4><p>Deleting a meal's entries one by one is slow.</p></div>
      <div><h4>What changes</h4><ul><li>Clear on each meal with entries, with a confirmation.</li></ul></div>
      <div><h4>What stays</h4><ul><li>+ Add food and Copy.</li></ul></div></div>`,
    css: ".diary .mealactions { flex-wrap: wrap; }",
    cards: { diary: "metron-food-diary-card" },
    pairs: [
      {
        id: "B1",
        title: "Food diary: a meal with food in it",
        text: "Clear joins + Add food and Copy on each meal that has entries.",
        before: card(breakfast, { clear: false }),
        after: card(breakfast),
        marks: { after: [[t$("clear"), "new"]] },
      },
    ],
    flows: [
      {
        id: "H1",
        title: "Clear breakfast",
        device: "phone",
        group: "happy",
        steps: [
          step(card(breakfast), "Breakfast has two entries. Tap Clear.", t$("clear")),
          step(card(breakfast, { panel: confirm() }), "A confirmation says what goes. Tap Clear again.", t$("really-clear")),
          step(card([]), "Breakfast is empty."),
        ],
      },
      {
        id: "E1",
        title: "Change your mind",
        device: "laptop",
        group: "edge",
        steps: [
          step(card(breakfast, { panel: confirm() }), "Cancel…", t$("cancel")),
          step(card(breakfast), "…keeps every entry."),
        ],
      },
    ],
  });
}

module.exports = { build };

if (require.main === module) {
  if (!process.argv[2]) {
    console.error("usage: node design/drafts/example.js <out.html>");
    process.exit(2);
  }
  build(process.argv[2]).then(() => console.log("wrote", process.argv[2]));
}
