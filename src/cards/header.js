// The Fork & Scale cards.
//
// custom:fork-and-scale-food-diary-card   one person's day, meal by meal: add, change,
//                                         delete and copy food
// custom:fork-and-scale-foods-card        the house's saved foods, per 100 g
// custom:fork-and-scale-weight-card       one person's weight: log it, and chart it with
//                                         the BMI bands and their goal
// custom:fork-and-scale-trends-card       one person's calories by day or week, by meal,
//                                         against their goal
// custom:fork-and-scale-summary-card      one person's day at a glance: calorie and macro
//                                         rings, meals, and weight
//
// They talk to the integration over its websocket commands, and redraw when
// its fork_and_scale/subscribe events say something changed.
//
// Config for the cards that show one person (all but saved foods):
//   person  a person's name; defaults to the person linked to the logged-in user
//   title   optional heading
//   locale  optional language code; defaults to Home Assistant's language
//
// The summary card also takes:
//   navigation_path  optional dashboard path to open when the card is tapped
//
// Saved foods config:
//   title, locale  as above
