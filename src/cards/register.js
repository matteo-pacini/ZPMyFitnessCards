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
      type: "metron-food-diary-card",
      name: "Food diary",
      description: "One person's food for a day, meal by meal, from Metron",
      documentationURL: "https://github.com/matteo-pacini/metron#food-diary-card",
    },
    {
      element: FoodsCard,
      type: "metron-foods-card",
      name: "Saved foods",
      description: "The foods saved in Metron, per 100 g",
      documentationURL: "https://github.com/matteo-pacini/metron#saved-foods-card",
    },
    {
      element: MealsCard,
      type: "metron-meals-card",
      name: "Saved meals",
      description: "The meals saved in Metron, everyone's and each person's",
      documentationURL: "https://github.com/matteo-pacini/metron#saved-meals-card",
    },
    {
      element: WeightCard,
      type: "metron-weight-card",
      name: "Weight",
      description: "Log weight, and chart it with the BMI bands and the goal, from Metron",
      documentationURL: "https://github.com/matteo-pacini/metron#weight-card",
    },
    {
      element: TrendsCard,
      type: "metron-trends-card",
      name: "Trends",
      description: "Calories by day or week, by meal, against the goal, from Metron",
      documentationURL: "https://github.com/matteo-pacini/metron#trends-card",
    },
    {
      element: SummaryCard,
      type: "metron-summary-card",
      name: "Fitness summary",
      description: "One person's day at a glance: calories, macros, meals and weight, from Metron",
      documentationURL: "https://github.com/matteo-pacini/metron#summary-card",
    },
    {
      element: StreakCard,
      type: "metron-streak-card",
      name: "Streak",
      description: "One person's days in a row on their calorie goal, and the last 30 days, from Metron",
      documentationURL: "https://github.com/matteo-pacini/metron#streak-card",
    },
  ];
  window.customCards = window.customCards || [];
  for (const { element, ...card } of cards) {
    window.customElements.define(card.type, element);
    window.customCards.push(card);
  }
});
