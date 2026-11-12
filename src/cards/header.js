// The Metron cards.
//
// custom:metron-food-diary-card  one person's day, meal by meal: add, change,
//                                delete and copy food, add and save meals
// custom:metron-foods-card       the house's saved foods, per 100 g, and who
//                                saved each
// custom:metron-meals-card       the house's saved meals: everyone's, and each
//                                person's own
// custom:metron-weight-card      one person's weight: log it, and chart it with
//                                the BMI bands and their goal
// custom:metron-trends-card      one person's calories by day or week, by meal,
//                                against their goal
// custom:metron-summary-card     one person's day at a glance: calorie and macro
//                                rings, meals, and weight
//
// They talk to the integration over its websocket commands, and redraw when
// its metron/subscribe events say something changed.
//
// Config, which each card's visual editor also sets (editor.js). For the cards
// that show one person (all but saved foods and saved meals):
//   person  a person's name; defaults to the person linked to the logged-in user
//   title   optional heading
//   locale  optional language code; defaults to Home Assistant's language
//
// The summary card also takes:
//   navigation_path  optional dashboard path to open when the card is tapped
//
// Saved foods config:
//   title, locale  as above
//
// Saved meals config:
//   person         a person's name: shows everyone's meals and theirs, and new
//                  meals are theirs; without it, every meal shows
//   title, locale  as above
