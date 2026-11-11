# AGENTS.md

Fork & Scale is a Home Assistant custom integration, `fork_and_scale`, with dashboard cards. HACS installs it as an integration, and the integration serves the cards' JavaScript itself.

## Layout

- `custom_components/fork_and_scale/`: the integration. `brand/` holds its icons.
  - `db.py`: the database, SQLite or Postgres, through SQLAlchemy Core, with blocking methods. `data.py` (`FitnessData`) is the only caller, except for the person form's `key_for_name`.
  - `goals.py`: calorie, macro and BMI maths, and conversions between kg and lb and between cm and feet and inches, with no Home Assistant code.
  - `coordinator.py` and `sensor.py`: each person's sensors, refreshed on every change and at midnight.
  - `websocket.py`: the commands the cards call.
  - `services.py`: the actions, `log_weight`, `log_food` and `get_day`, which name a person by their device. `services.yaml` gives their fields and selectors, and `translations/` their names, descriptions and errors; `tests/integration/test_services.py` checks the three agree.
  - `config_flow.py`: the integration and its people, one config sub-entry each.
  - `backup.py`: pauses writes while Home Assistant backs up.
  - `history.py`: imports a person's weights and calorie totals from the recorder's statistics of older sensors.
  - `openfoodfacts.py`: searches Open Food Facts by name, for the cards' `fork_and_scale/openfoodfacts/search`, through its Search-a-licious service.
  - `myfitnesspal.py`: reads MyFitnessPal's Premium export (a ZIP or one of its CSVs) and its printable diary page saved as a complete web page into a `Diary`, with no Home Assistant code. `config_flow.py` uploads the file, asks for meals and the weight unit, and writes through `FitnessData.async_replace_entries`.
  - `export.py`: a person's entries, weights and every saved food as a ZIP of CSVs, served by an admin-only view; "Export data" shows a signed link to it.
- `custom_components/fork_and_scale/frontend/fork-and-scale-cards.js`: generated from `src/` by `scripts/build.js`. Never edit it by hand. Commit it rebuilt, together with every change to `src/`.
- `src/cards/`: the cards, as plain browser scripts with no imports and no npm dependencies. `scripts/build.js` puts them, in the order of its `SOURCES`, into one block of the bundle, where they share one scope. Each card has a file of its own: `food-diary-card.js`, `foods-card.js`, `weight-card.js`, `trends-card.js` and `summary-card.js`. The rest are shared:
  - `header.js`: the comment that lists the cards and their config.
  - `strings.js`: `STRINGS` and `translate`.
  - `strings/`: a file per language, named for its tag, such as `en.js` or `pt-BR.js`, that puts that language's strings in `STRINGS`.
  - `helpers.js`: days, totals, `findPerson` and their kin, and the base style.
  - `food-form.js`: the food form, Open Food Facts and the scanner, for the food diary and saved foods cards.
  - `fitness-card.js`: `FitnessCard`, the base of every card: config, language, loading and live updates.
  - `food-card.js`: `FoodCard`, the base of the food diary and saved foods cards: barcode lookups and scans, Open Food Facts searches, and errors in the card's open panel.
  - `editor.js`: the visual editor every card opens, with a field for each option in the card's static `options`, drawn with the frontend's `ha-form`.
  - `charts.js` and `weights.js`: chart helpers, and weight units and BMI bands, for more than one card.
  - `person-card.js`: `PersonCard`, the base of the cards that show one person.
  - `register.js`: defines the cards and their editor once the frontend is ready.
- `tests/fixtures/myfitnesspal/`: made-up MyFitnessPal files with the real ones' quirks. The ZIP is built from its folder at test time.
- `tests/conftest.py`: a throwaway Postgres server for the session, on a Unix socket under `/tmp`, and a fresh database per test. `database_url` runs a test once on SQLite and once on Postgres.
- `tests/schemas.py`: databases at a given schema version, with sample data, and a trigger that makes a version bump fail, for the migration tests in `tests/integration/test_migrations.py` and `tests/e2e/test_migrations.py`.
- `tests/integration/`: pytest with `pytest-homeassistant-custom-component`, in a test instance of Home Assistant.
- `tests/cards/`: Node's built-in test runner. `harness.js` runs the cards' scripts, in the bundle's order, in one `vm` context with a stubbed DOM, for the pure functions and the markup they build. Interaction is tested end to end.
- `tests/e2e/test_card_states.py`: cards mounted straight into the running Home Assistant page, with a connection that fails on purpose, for the loading, failure and retry paths a dashboard rarely shows.
- `tests/e2e/`: pytest and Playwright against a brand-new Home Assistant, started from `.venv`, onboarded and set up by `conftest.py`. The whole suite runs twice, on SQLite and on Postgres. Chromium sees only the fonts in `nix/fonts.nix`, never the host's. Tests share one Home Assistant per database, so give the data each test adds unique names. That Home Assistant searches Open Food Facts on a fake Search-a-licious, which the `search` fixture tells what to find. `screenshots.py` takes the README images.
- `images/`: the README screenshots, from `scripts/screenshots`.

## Commands

Work inside the Nix dev shell: `nix develop`, or direnv with `.envrc`. Entering it runs `uv sync`, which creates `.venv`.

```sh
node scripts/build.js                                    # rebuild the cards' bundle
node scripts/build.js --check                            # CI: fail if it is stale
node --experimental-vm-modules --test 'tests/cards/*.test.js'
pytest --cov                                             # integration tests; fails under 90% coverage
scripts/e2e                                              # end-to-end tests (Linux)
scripts/screenshots                                      # retake images/ (Linux)
ruff check . && ruff format --check .
```

CI runs all of these through `nix develop -c` on every pull request and on master, plus hassfest and the HACS validator, and puts both coverage reports on the run's summary page.

`nix develop .#android` (x86_64-linux only) adds an Android SDK and a `pixel_8` AVD: a Pixel 8 on the Android 37.2 Play Store image with 16 KB pages and the host keyboard on, for the Home Assistant Companion app, whose APK is in `$COMPANION_APK`. Start it with `emulator -avd pixel_8`; the `emulator` and `adb` on its PATH are wrappers that run under `steam-run`, for the host GPU, and with `HOME` set to `.android/`. Every AVD, key and emulator file lives in `.android/`, which git ignores; delete it to start over. `create-avd` writes the AVD; `nix/android.nix` defines the SDK, the AVD and the app for both this shell and the VM test.

The same tests also run inside NixOS VMs with no network (`nix/e2e-vm.nix`), with Python from `uv.lock` through uv2nix (`nix/python.nix`):

```sh
nix build .#checks.x86_64-linux.e2e-vm-sqlite       # tests/e2e in Chromium, on SQLite
nix build .#checks.x86_64-linux.e2e-vm-postgresql   # the same, on Postgres
nix build .#checks.x86_64-linux.android-vm          # tests/e2e/test_android.py; needs nested KVM
scripts/android-vm [dir]                            # the same, keeping screenshots and logs in dir
```

When several worktrees run tests at once, run the heavy ones through `scripts/throttle`, which holds them together to half of the machine's CPU threads:

```sh
scripts/throttle 1 pytest --cov
scripts/throttle 2 scripts/e2e
scripts/throttle 4 nix build -L .#checks.x86_64-linux.e2e-vm-sqlite
```

`tests/e2e/test_android.py` boots a fresh AVD, installs the Companion app, takes it through its first run against a Home Assistant that lets 127.0.0.1 in without a password, turns on the app's WebView remote debugging, and drives the cards in the app through Playwright over `adb forward`. The emulator's camera cannot show a barcode, so the scan test checks that the app's scanner opens, then sends the result the app would. It is skipped unless `COMPANION_APK` is set. CI does not run it: nested KVM on the runners is far too slow. Run it locally with `scripts/android-vm`, which keeps its screenshots, logcat and emulator log whether it passes or fails.

## Rules that are easy to break

- **Versions move together.** `pytest-homeassistant-custom-component` pins one Home Assistant release. The e2e packages in `pyproject.toml`, `home-assistant-frontend` and the rest, are pinned to what that release's manifests ask for. Playwright for Python must equal the Nix shell's `playwright-driver`; the e2e tests check it.
- **Schemas.** Import `vol` from `schema.py`, never `voluptuous` or `probatio` directly. Newer Home Assistant releases only accept probatio schemas and older ones only voluptuous, and the integration supports both (`hacs.json` sets the minimum).
- **Card events.** Cards redraw by setting `innerHTML`, so they handle events by delegation: a `data-action` attribute on the element, and a `kind:action` handler in the class's static `actions`. Redraw only the part that changed while someone types, or the input loses focus.
- **Card registration.** Define cards on `window.customElements` only after `customElements.whenDefined("home-assistant")`. The frontend swaps in its own registry as it boots and ignores cards defined before that.
- **Loading the cards.** `add_extra_js_url` puts the bundle only in pages served after the integration is set up. A page already open when it is first added never loads the cards, and shows "Configuration error" for them until reloaded; the setup's success message (`config.create_entry.default`) says so. Before Home Assistant 2026.11.0, the frontend's service worker also starts the companion apps from the start page it cached at its last update, so the apps miss the cards on every cold start until reloaded. The README's Troubleshooting section covers both; keep it in step.
- **Screenshots.** The README's images must always show the cards and flows as they are. A change to anything a person sees retakes the screenshots it touches with `scripts/screenshots`, in the same change, and a new thing a person sees gets a screenshot and a place in the README. Keep only images that changed for a real reason: revert those that differ only because the sample data is dated relative to today.
- **Install steps.** `tests/integration/test_readme.py` checks where the README's my.home-assistant.io buttons lead, and `tests/e2e/test_install.py` follows the README's steps in the browser, from its "Add integration" link to a card. Change those tests with the steps.
- **New card.** Give it a file in `src/cards/`, and add it to `SOURCES` in `scripts/build.js` after the file of the class it extends and before `register.js`. In `register.js`, define it and register it in `window.customCards` with `documentationURL` set to its README anchor. Give it a static `options`, the options its visual editor shows; an option no card has had yet needs a field in `EDITOR_FIELDS` in `editor.js` and an `editor_<option>` string. Add its element name to `tests/cards/bundle.test.js`, and give it a README section with screenshots.
- **Shared scope.** The cards' files share one block of the bundle on purpose: each can use what the others declare, and no two can declare the same name. What runs as the bundle loads, such as a class's `extends` and static fields or a constant's value, can only use names declared before it in the `SOURCES` order. The bundle loads as a module, so it is strict code. Still never declare globals except `window.customCards`.
- **Languages.** The cards speak 11 languages: en, de, es, fr, it, nl, pl, pt, pt-BR, sv and zh-Hans. Each has a file in `src/cards/strings/` that sets its entry in the shared `STRINGS` table. Add a key to `en.js` first, then to every other language's file. `pt-BR.js` holds only what Brazilian Portuguese says differently from `pt.js`, so a key goes there only when it does. The tests check keys and placeholders, and that each file is in the bundle. To add a language, give it a file named for its tag, list it in `SOURCES` in `scripts/build.js` after `cards/strings.js`, with `en.js` first and the rest in alphabetical order, and raise the count of languages in `tests/cards/fitness-cards.test.js`. Its `language_name` is its name in itself, which the editor's language dropdown shows; add it to that dropdown's list in `tests/cards/editor.test.js`. Give the integration the same language too: a `translations/` file and its tag in `LANGUAGES` in `tests/integration/test_translations.py`. Add it to the dropdown, and the count, in `.github/ISSUE_TEMPLATE/translation.yml`.
- **Theming.** Take colours and fonts from Home Assistant theme variables, never hard-coded colours.
- **People.** Each person is a config sub-entry. Code refers to a person by the `key` in its data, never by name or sub-entry ID. Re-adding a removed person under the same name reuses their key, which brings back their data, entities and history. The form finds that key with `key_for_name`, on a connection of its own, since the entry may be reloading after the last person added, or may have failed to set up. Setup listens for changes to its people before it reads them, so a person added while it runs loads with the reload that follows.
- **Units.** Everything is stored, and sent and taken by the websocket commands, in kg and cm. Only what a person reads or types follows Home Assistant's unit system: lb, feet and inches when it is US customary (`uses_pounds` in `data.py`, `weightUnit` in the cards), else kg and cm. Convert only where values come in or go out: in the person form, the actions and the cards, and as an imported file in another unit is read (`weights_kg` in `myfitnesspal.py`). Food stays in grams and energy in kcal.
- **Writes.** Go through `FitnessData`, never `Database` directly. It runs the query in the executor, holds the lock that backups pause on, refreshes goals, corrects the recorder's statistics for past days, and sends `SIGNAL_CHANGED` to the sensors and the cards.
- **Both databases.** Every query must work on SQLite and Postgres: build it with SQLAlchemy Core, not raw SQL, and test it through `database_url`. Days are ISO date strings in both.
- **Schema.** `MIGRATIONS` in `db.py` upgrades a database one version at a time, and `schema_version` records where it is. Never edit a released migration or `_schema_v1`; add a new schema function and a migration to it. Each migration commits with its version bump or not at all, on both databases: on SQLite only because `make_engine` begins every transaction itself, since Python's `sqlite3` would commit DDL such as `ALTER TABLE` on its own. Keep that. A database at a version newer than `MIGRATIONS` knows is refused unchanged (`NewerSchemaError`), and setup says so. `tests/integration/test_migrations.py` fails each migration midway in turn, so a new migration is tested by adding it; keep `add_version_1_sample` in `tests/schemas.py` working on the new version.
- **Cleanup.** Tests create nothing outside temporary folders and the throwaway Postgres server, and remove both even when they fail.
- **Daily totals.** Use `state_class: total` with `last_reset` at local midnight, never `total_increasing`: deleting an entry lowers a total, which `total_increasing` would read as a meter reset.
- **Integration strings.** `translations/*.json` cover the same 11 languages as the cards. `tests/integration/test_translations.py` checks each matches `en.json`.
- **Open Food Facts.** Tests never call the real service. The barcode lookup runs in the browser, and tests answer it with Playwright's `page.route`. Search by name runs on the Home Assistant server, in `openfoodfacts.py`, because Search-a-licious refuses browsers from other sites. Integration tests answer it with `aioclient_mock`. The e2e tests answer it with `FakeSearch` in `tests/e2e/conftest.py`, a local server that the test Home Assistant reaches through the `FORK_AND_SCALE_SEARCH_URL` environment variable. That variable is only for tests: keep it out of the config flow, options and `configuration.yaml`.
- **App scanner.** `scanWithApp` wraps `hass.auth.external.receiveMessage`, which the frontend does not document. Keep calling the original handler, which acknowledges each message, and keep typing a barcode working without any scanner.
- **Coverage.** CI fails if the Python tests cover less than 90% of the integration's lines and branches (`fail_under` in `pyproject.toml`), and reports card unit coverage without enforcing it. Test new code anyway: card code needs a unit test for its pure functions and an end-to-end test for each interaction and failure path.
- **MyFitnessPal files.** A saved printable diary holds the account's email, location and sign-in tokens. Read only the diary's rows, never store or log the file, and name a line or row in errors, never the file's text. `.private/` holds real files for local checks only; fixtures are made up. `.mhtml` is not supported: Chromium uploads it as `multipart/related`, which Home Assistant's `/api/file_upload` rejects.
- **Entry sources.** `entries.source` is `myfitnesspal` for imported entries and NULL for everything logged in Home Assistant. Importing again deletes and re-adds only that source's entries, from the file's first day to its last.
- **Links in flows.** The frontend opens links to its own origin in place, so a markdown link to a download only navigates. The export link is an HTML `<a target="_blank">`, passed as the `{link}` and `{link_end}` placeholders because translations may not contain HTML.
- **Uploads in tests.** `file_upload` keeps files in the system's temporary folder. Integration tests point `tempfile.tempdir` at `tmp_path`, and the end-to-end Home Assistant gets a `TMPDIR` inside its configuration folder.
- **Frozen time.** The integration tests freeze time, so `asyncio.sleep` with a delay never returns there. Yield with `asyncio.sleep(0)`.

## Style

- Match the surrounding code. Comments say why, not what.
- The README is plain, short sentences.
- Commit subjects are short imperative sentences, with no type prefix.
