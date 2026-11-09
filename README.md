# ZPMyFitnessCards

A food diary and weight tracking for everyone in your home, inside Home Assistant.

ZPMyFitnessCards is a Home Assistant integration with its own dashboard cards. You log each food you eat by weight and meal, and your weight once a day. The integration keeps every entry in an SQLite database in your configuration folder, and exposes daily calories, macros and weight as sensors.

It is in early development. The integration, its sensors and all five cards work; barcode scanning comes next.

## Install

1. In HACS, add `https://github.com/matteo-pacini/ZPMyFitnessCards` as a custom repository of type Integration, then download ZPMyFitnessCards.
2. Restart Home Assistant.
3. In **Settings > Devices & services**, add **ZPMyFitnessCards**, and choose where it keeps its data (see [Database](#database)).
4. On its page, use **Add person** for each person.

Each person has a name, sex, birth date, height, starting weight and date, goal weight, activity level and weekly pace. From these the integration works out a calorie goal with the Mifflin-St Jeor formula, and follows it as the weight changes. You can type your own calorie goal instead, and set the protein, carbs and fat split, which defaults to 20%, 50% and 30%.

To change a person later, use **Change person**. Its **Delete all data** option erases their food, weights and goals.

**Import history**, in the same menu, copies a person's past from sensors the recorder has kept: each day's average from a weight sensor, for days with no weight yet, and each day's total from a calories sensor, as one "Imported total" entry under Snacks. Running it again adds only what is missing. Removing a person keeps their data, and adding them back under the same name brings it back.

The integration loads the cards for you. There is no dashboard resource to add.

Requires Home Assistant 2025.3 or later.

## Sensors

Each person is a device with these sensors, named after them, for example `sensor.debora_calories_today`:

| Sensor | Unit | Notes |
| --- | --- | --- |
| Calories, protein, carbs, fat, fibre, sugar, saturated fat and salt today | kcal or g | Start again at midnight. |
| Breakfast, lunch, dinner and snacks calories | kcal | Start again at midnight. |
| Calories remaining | kcal | Calorie goal minus calories today. |
| Calorie, protein, carbs and fat goal | kcal or g | |
| Weight | kg | The last weigh-in, or the starting weight before the first. |
| Weight change | kg | Since the starting weight. |
| Daily burn | kcal | Estimated calories burnt a day. |

The weight sensor also has these attributes: `underweight_below_kg`, `overweight_from_kg` and `obese_from_kg` (the BMI band limits for the person's height), `bmi_band`, `goal_weight_kg`, `height_cm` and `weighed_on`.

The daily totals keep long-term statistics, so a statistics graph with `stat_types: change` and `period: day` shows each day's intake. Changing a past day in the diary also corrects its statistics.

## Database

When you add the integration, you choose where its data lives:

- **SQLite**, the default: a file, `zp_my_fitness.db`, in the configuration folder. Home Assistant backups include it, and pause writes while they copy it.
- **Postgres**: a database you run, given as a URL such as `postgresql://user:password@192.168.1.10:5432/zp_my_fitness`. Create an empty database for it first; don't share the one Home Assistant's recorder uses. The integration creates its tables and checks the connection before saving. Home Assistant backups do not include it, so back it up yourself, for example with `pg_dump`. Home Assistant stores the URL, password included, in its configuration, as it does the recorder's.

Postgres needs the psycopg2 driver. If your recorder already runs on Postgres with a `postgresql://` URL, Home Assistant has it; if not, setup says it is missing.

## Cards

### Food diary card

One person's day, meal by meal: the calorie goal, what they have eaten and what is left, protein, carbs and fat against their goals, and each meal's entries.

<img src="images/food-diary.png" alt="Food diary" width="400">

- **Add food** under a meal opens three tabs. **Saved foods** searches your saved foods, or lists the ones you logged recently; choose one, then type the grams or tap a portion. **Quick add** logs a name and calories without saving a food. **New food** saves a food and logs it.
- Tap an entry to change its grams or meal, or to delete it.
- **Copy** fills a meal from any meal on another day.
- The arrows and the calendar move between days. Future days are not allowed.

<img src="images/food-diary-add.png" alt="Adding food" width="400">

It follows Home Assistant's theme, light or dark, and its language.

<img src="images/food-diary-dark.png" alt="Food diary in dark mode" width="400">

```yaml
type: custom:zp-food-diary-card
person: Debora
```

| Option | Description |
| --- | --- |
| `person` | Optional. The name of a person added to the integration. Without it, the card shows the person linked to whoever is logged in. |
| `title` | Optional. Replaces "Food diary". |
| `locale` | Optional. A language code such as `it` or `pt-BR`. Defaults to Home Assistant's language. |

### Saved foods card

The foods everyone in the house shares, with their values per 100 g. Search them, add new ones, and tap one to change or delete it. A food can have a barcode, the optional fibre, sugar, saturated fat and salt, and portions such as "Slice, 36 g", which the diary offers as shortcuts. Changing a food leaves entries already logged from it as they were.

<img src="images/saved-foods.png" alt="Saved foods" width="400">

```yaml
type: custom:zp-foods-card
```

| Option | Description |
| --- | --- |
| `title` | Optional. Replaces "Saved foods". |
| `locale` | Optional. As for the food diary card. |

### Weight card

One person's weight: the latest weigh-in, the change since their starting weight, and their BMI band. The chart covers 90 days, 1 year or all of it, shaded by BMI band for the person's height, with a dashed line at the goal weight. Log a weight for today or any past day; a day keeps one weight, so logging again replaces it. The last five weigh-ins are listed, each with a button to delete it.

<img src="images/weight.png" alt="Weight" width="400">

```yaml
type: custom:zp-weight-card
person: Matteo
```

### Trends card

One person's calories, stacked by meal, with a mark at each day's calorie goal. 7 and 30 days show a bar a day; tap one to open that day in a food diary on the same dashboard. 90 days and 1 year show a bar a week, averaging the days logged that week. Above the chart: the average calories a day, the days at or under goal, and the share of energy from protein, carbs and fat. These count complete days only, not today. Goals are recorded from the day a person is added, so earlier days have none.

<img src="images/trends.png" alt="Trends over 30 days" width="400">

<img src="images/trends-week.png" alt="Trends over 7 days" width="400">

```yaml
type: custom:zp-trends-card
person: Debora
```

### Summary card

One person's day at a glance, for a main dashboard: a ring of the calories eaten against the goal, with what is left (or over) in the middle; rings for protein, carbs and fat; a bar splitting the day's calories by meal; and the latest weight with its BMI band, the change over 30 days and a sparkline. It moves to the new day at midnight.

<img src="images/summary.png" alt="Summary" width="400">

<img src="images/summary-dark.png" alt="Summary in dark mode" width="400">

```yaml
type: custom:zp-summary-card
person: Debora
navigation_path: /dashboard-meds/debora
```

| Option | Description |
| --- | --- |
| `navigation_path` | Optional. A dashboard path to open when the card is tapped, such as the dashboard with the full diary. |

The weight, trends and summary cards take the same `person`, `title` and `locale` options as the food diary card.

All five cards come in English, German, Spanish, French, Italian, Dutch, Polish, Portuguese, Brazilian Portuguese, Swedish and Simplified Chinese.

## Development

See [AGENTS.md](AGENTS.md) for the layout and commands. Everything runs in the Nix dev shell:

```sh
nix develop
pytest && scripts/e2e
scripts/screenshots   # retake the images in images/
```

## Licence

GNU Affero General Public License, version 3 or any later version (AGPL-3.0-or-later). See [LICENSE](LICENSE).
