// Home Assistant's frontend replaces window.customElements with its own
// registry as it boots, and only finds cards defined there. The integration
// loads the cards' bundle alongside the frontend, so wait for the frontend's
// own <home-assistant> element, which it defines once that registry is in
// place.
customElements.whenDefined("home-assistant").then(() => {
  window.customElements.define(EDITOR, CardEditor);
  // Each card's element, then what the dashboard's card picker shows of it.
  const cards = [
    {
      element: FoodDiaryCard,
      type: "fork-and-scale-food-diary-card",
      name: "Food diary",
      description: "One person's food for a day, meal by meal, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#food-diary-card",
    },
    {
      element: FoodsCard,
      type: "fork-and-scale-foods-card",
      name: "Saved foods",
      description: "The foods saved in Fork & Scale, per 100 g",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#saved-foods-card",
    },
    {
      element: MealsCard,
      type: "fork-and-scale-meals-card",
      name: "Saved meals",
      description: "The meals saved in Fork & Scale, everyone's and each person's",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#saved-meals-card",
    },
    {
      element: WeightCard,
      type: "fork-and-scale-weight-card",
      name: "Weight",
      description: "Log weight, and chart it with the BMI bands and the goal, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#weight-card",
    },
    {
      element: TrendsCard,
      type: "fork-and-scale-trends-card",
      name: "Trends",
      description: "Calories by day or week, by meal, against the goal, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#trends-card",
    },
    {
      element: SummaryCard,
      type: "fork-and-scale-summary-card",
      name: "Fitness summary",
      description: "One person's day at a glance: calories, macros, meals and weight, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#summary-card",
    },
  ];
  window.customCards = window.customCards || [];
  for (const { element, ...card } of cards) {
    window.customElements.define(card.type, element);
    window.customCards.push(card);
  }
});
