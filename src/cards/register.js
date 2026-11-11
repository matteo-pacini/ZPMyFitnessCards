// Home Assistant's frontend replaces window.customElements with its own
// registry as it boots, and only finds cards defined there. The integration
// loads this file alongside the frontend, so wait for the frontend's own
// <home-assistant> element, which it defines once that registry is in place.
customElements.whenDefined("home-assistant").then(() => {
  window.customElements.define("fork-and-scale-food-diary-card", FoodDiaryCard);
  window.customElements.define("fork-and-scale-foods-card", FoodsCard);
  window.customElements.define("fork-and-scale-weight-card", WeightCard);
  window.customElements.define("fork-and-scale-trends-card", TrendsCard);
  window.customElements.define("fork-and-scale-summary-card", SummaryCard);
  window.customCards = window.customCards || [];
  window.customCards.push(
    {
      type: "fork-and-scale-food-diary-card",
      name: "Food diary",
      description: "One person's food for a day, meal by meal, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#food-diary-card",
    },
    {
      type: "fork-and-scale-foods-card",
      name: "Saved foods",
      description: "The foods saved in Fork & Scale, per 100 g",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#saved-foods-card",
    },
    {
      type: "fork-and-scale-weight-card",
      name: "Weight",
      description: "Log weight, and chart it with the BMI bands and the goal, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#weight-card",
    },
    {
      type: "fork-and-scale-trends-card",
      name: "Trends",
      description: "Calories by day or week, by meal, against the goal, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#trends-card",
    },
    {
      type: "fork-and-scale-summary-card",
      name: "Fitness summary",
      description: "One person's day at a glance: calories, macros, meals and weight, from Fork & Scale",
      documentationURL: "https://github.com/matteo-pacini/fork-and-scale#summary-card",
    },
  );
});
