# ZPMyFitnessCards

A food diary and weight tracking for everyone in your home, inside Home Assistant.

ZPMyFitnessCards is a Home Assistant integration with its own dashboard cards. You log each food you eat by weight and meal, and your weight once a day. The integration keeps every entry in an SQLite database in your configuration folder, and exposes daily calories, macros and weight as sensors.

It is in early development. The integration, its sensors, all five cards and barcodes work.

## Install

1. Open the repository in HACS with this button, then download ZPMyFitnessCards. Or, in HACS, add `https://github.com/matteo-pacini/ZPMyFitnessCards` as a custom repository of type Integration.

   [![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=matteo-pacini&repository=ZPMyFitnessCards&category=integration)

2. Restart Home Assistant.
3. Add the integration with this button, or add **ZPMyFitnessCards** in **Settings > Devices & services**. Choose where it keeps its data (see [Database](#database)).

   [![Open your Home Assistant instance and start setting up ZPMyFitnessCards.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=zp_my_fitness)

4. On its page, use **Add person** for each person.

Each person has a name, sex, birth date, height, starting weight and date, goal weight, activity level and weekly pace. From these the integration works out a calorie goal with the Mifflin-St Jeor formula, and follows it as the weight changes. You can type your own calorie goal instead, and set the protein, carbs and fat split, which defaults to 20%, 50% and 30%.

To change a person later, use **Change person**. Its **Delete all data** option erases their food, weights and goals.

**Import history**, in the same menu, copies a person's past from sensors the recorder has kept: each day's average from a weight sensor, for days with no weight yet, and each day's total from a calories sensor, as one "Imported total" entry under Snacks. Running it again adds only what is missing. Removing a person keeps their data, and adding them back under the same name brings it back.

The menu also imports a diary from MyFitnessPal and exports a person's data. See [Import and export](#import-and-export).

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

## Actions

Automations, scripts and Assist can log and read with three actions. Each takes a person, chosen by their device, and a day, which is today if left out. Future days are refused.

- `zp_my_fitness.log_weight` records a weight in kg, from 20 to 400. A day keeps one weight, so logging again replaces it.
- `zp_my_fitness.log_food` logs food under a meal: `breakfast`, `lunch`, `dinner` or `snacks`. Give either a saved food, by `food` (its name, in any case) or `barcode`, with its `grams`; or a quick add, with a `name` and `kcal`, and if you like `protein`, `carbs` and `fat`.
- `zp_my_fitness.get_day` returns a person's day: each meal's entries and totals, the day's totals, the goals and the weight, all to 0.1.

Choose the person in the action editor, which fills in their `device_id`. For example, to log each new reading from a smart scale:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.bathroom_scale_weight
    not_to: [unavailable, unknown]
actions:
  - action: zp_my_fitness.log_weight
    data:
      device_id: 5f1c0d7e9a2b4c6d8e0f1a2b3c4d5e6f
      weight: "{{ trigger.to_state.state }}"
```

And to send the day's calories at night:

```yaml
actions:
  - action: zp_my_fitness.get_day
    data:
      device_id: 5f1c0d7e9a2b4c6d8e0f1a2b3c4d5e6f
    response_variable: day
  - action: notify.notify
    data:
      message: "{{ day.totals.kcal | round }} of {{ day.goals.kcal | round }} kcal today"
```

## Import and export

### From MyFitnessPal

**Import from MyFitnessPal**, in a person's **Change person** menu, brings in their diary. It takes either of these:

- **The Premium export**: the ZIP MyFitnessPal sends, `File-Export-<from>-to-<to>.zip`, or any CSV file in it. Each meal of each day becomes one quick add called "MyFitnessPal", with its calories, protein, carbs, fat, fibre, sugar, saturated fat and salt (worked out from sodium). Weights come from the measurements; the export does not say their unit, so the form asks for kg or lb. It suggests the unit of the export's exercise file, or else Home Assistant's own. Other measurements, exercise and notes are left out. A CSV saved again from Excel works too, with dates such as 25/10/2025 or 10/25/2025: each file's dates are read in the order they show, and month first when they could be either.
- **The printable diary**: on MyFitnessPal's website, open the printable diary (`/reports/printable-diary/<your user name>`) for the days you want and wait for it to show. Save it with your browser's Save Page As as a complete web page: "Web Page, complete" in Firefox, "Webpage, Complete" in Chrome and Edge. Then choose the `.html` file. Each food becomes a quick add with its values as the page shows them. A food logged in grams keeps its grams; any other amount stays in its name, such as "Chicken wrap, 1 wrap". The dates on the page must be in English.

Meals called breakfast, lunch, dinner or supper, and snacks find their meal by name. If the file has meals of its own, the form asks where each goes. Importing again replaces the person's MyFitnessPal entries on the days the file covers, from its first day to its last, and never touches food logged in Home Assistant. A weight is added only on a day that has none. Days after today are left out, and no saved foods are made. Statistics for past days are corrected, as for any change to the diary.

A saved printable diary also holds your MyFitnessPal account's email address, location and sign-in tokens. Home Assistant reads the diary's rows and keeps nothing else: it deletes the uploaded file once read, and never logs what is in it. Delete your own copy when you are done.

### Export data

**Export data**, in the same menu, shows a link to a ZIP of the person's data, as CSV files in metric units:

- `entries.csv`: every entry, with its day, meal, name, grams, kcal and nutrients in g, the saved food it came from, `myfitnesspal` for imported entries, and when it was logged.
- `weights.csv`: each day's weight in kg.
- `foods.csv`: the saved foods, with their values per 100 g, barcodes and portions. This is the household's shared list, so it is the same for everyone.

The link works for five minutes, and only for administrators.

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

### Barcodes

Both the saved foods card and the food diary's **Add food** panel know barcodes.

- **Typing one** works on every device. In the saved foods card, type it in a food's Barcode field and tap **Look up barcode**. In the diary, type it in the search box: a saved food with that barcode shows up, and if there is none, **Look up … on Open Food Facts** fills in a new food.
- **Scanning one** shows a **Scan** button where the device can. In the Home Assistant app (Android 2024.6.1 or later, iOS 2024.5 or later) it opens the app's own scanner. In a browser that has a barcode reader built in, such as Chrome on Android, it opens the camera in the card.
- **Open Food Facts** fills in the name, the values per 100 g and a serving size from the barcode, straight from your browser. Check them against the label before saving. A barcode that a saved food already has opens that food instead.

<img src="images/barcode-lookup.png" alt="A food filled in from its barcode" width="400">

Scanning in the app relies on an undocumented part of Home Assistant's frontend; if an update changes it, the Scan button stops working there and typing still works.

### Open Food Facts search

The search boxes in the saved foods card and in the food diary's **Add food** panel can also search Open Food Facts by name.

- Type a name, then tap **Search Open Food Facts for "…"** under your saved foods. It searches only when you tap it, never as you type.
- It shows ten products at a time, and **More** shows the next ten. Each row has the name, brand, pack size and kcal per 100 g. Names are in the card's language when the product has one, else in English.
- It only finds products that give kcal, protein, carbs and fat per 100 g.
- Tap a product to open **New food**, filled in as from its barcode. If the barcode lookup fails, the values come from the search instead, with a warning. The search can be months behind Open Food Facts, and has no serving sizes.

<img src="images/food-search.png" alt="Searching Open Food Facts from the food diary" width="400">

Home Assistant runs this search, not your browser, so the Home Assistant server needs internet access. It sends Open Food Facts the words you typed and the card's language.

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

### In the Home Assistant app

The cards fit a phone's width. These are the food diary, summary, weight and trends cards in the Home Assistant app on Android.

<img src="images/phone-food-diary.png" alt="Food diary in the Home Assistant app" width="200"> <img src="images/phone-summary.png" alt="Summary in the Home Assistant app" width="200"> <img src="images/phone-summary-dark.png" alt="Summary in the Home Assistant app, dark mode" width="200"> <img src="images/phone-weight.png" alt="Weight in the Home Assistant app" width="200"> <img src="images/phone-trends.png" alt="Trends in the Home Assistant app" width="200">

## Development

See [AGENTS.md](AGENTS.md) for the layout and commands. Everything runs in the Nix dev shell:

```sh
nix develop
pytest --cov && scripts/e2e
scripts/screenshots         # retake the desktop images in images/
scripts/android-vm          # the cards in the Home Assistant app (Android emulator in a VM; needs nested KVM)
scripts/phone-screenshots   # retake the phone images with it
```

## Licence

GNU Affero General Public License, version 3 or any later version (AGPL-3.0-or-later). See [LICENSE](LICENSE).
