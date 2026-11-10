# AGENTS.md

ZPMyFitnessCards is a Home Assistant custom integration, `zp_my_fitness`, with dashboard cards. HACS installs it as an integration, and the integration serves the cards' JavaScript itself.

## Layout

- `custom_components/zp_my_fitness/`: the integration. `brand/` holds its icons.
  - `db.py`: the database, SQLite or Postgres, through SQLAlchemy Core, with blocking methods. `data.py` (`FitnessData`) is the only caller.
  - `goals.py`: calorie, macro and BMI maths, with no Home Assistant code.
  - `coordinator.py` and `sensor.py`: each person's sensors, refreshed on every change and at midnight.
  - `websocket.py`: the commands the cards call.
  - `services.py`: the actions, `log_weight`, `log_food` and `get_day`, which name a person by their device. `services.yaml` gives their fields and selectors, and `translations/` their names, descriptions and errors; `tests/integration/test_services.py` checks the three agree.
  - `config_flow.py`: the integration and its people, one config sub-entry each.
  - `backup.py`: pauses writes while Home Assistant backs up.
  - `history.py`: imports a person's weights and calorie totals from the recorder's statistics of older sensors.
- `custom_components/zp_my_fitness/frontend/zp-my-fitness-cards.js`: generated from `src/` by `scripts/build.js`. Never edit it by hand. Commit it rebuilt, together with every change to `src/`.
- `src/`: plain browser scripts, one per card or family of cards. `fitness-cards.js` holds every card: they share loading, live updates, the food form and the strings. There are no imports and no npm dependencies.
- `tests/conftest.py`: a throwaway Postgres server for the session, on a Unix socket under `/tmp`, and a fresh database per test. `database_url` runs a test once on SQLite and once on Postgres.
- `tests/integration/`: pytest with `pytest-homeassistant-custom-component`, in a test instance of Home Assistant.
- `tests/cards/`: Node's built-in test runner. `harness.js` loads a card script into a `vm` context with a stubbed DOM, for the pure functions and the markup they build. Interaction is tested end to end.
- `tests/e2e/test_card_states.py`: cards mounted straight into the running Home Assistant page, with a connection that fails on purpose, for the loading, failure and retry paths a dashboard rarely shows.
- `tests/e2e/`: pytest and Playwright against a brand-new Home Assistant, started from `.venv`, onboarded and set up by `conftest.py`. The whole suite runs twice, on SQLite and on Postgres. Tests share one Home Assistant per database, so give the data each test adds unique names. `screenshots.py` takes the README images.
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

`tests/e2e/test_android.py` boots a fresh AVD, installs the Companion app, takes it through its first run against a Home Assistant that lets 127.0.0.1 in without a password, turns on the app's WebView remote debugging, and drives the cards in the app through Playwright over `adb forward`. The emulator's camera cannot show a barcode, so the scan test checks that the app's scanner opens, then sends the result the app would. It is skipped unless `COMPANION_APK` is set. CI does not run it: nested KVM on the runners is far too slow. Run it locally with `scripts/android-vm`, which keeps its screenshots, logcat and emulator log whether it passes or fails.

## Rules that are easy to break

- **Versions move together.** `pytest-homeassistant-custom-component` pins one Home Assistant release. The e2e packages in `pyproject.toml`, `home-assistant-frontend` and the rest, are pinned to what that release's manifests ask for. Playwright for Python must equal the Nix shell's `playwright-driver`; the e2e tests check it.
- **Schemas.** Import `vol` from `schema.py`, never `voluptuous` or `probatio` directly. Newer Home Assistant releases only accept probatio schemas and older ones only voluptuous, and the integration supports both (`hacs.json` sets the minimum).
- **Card events.** Cards redraw by setting `innerHTML`, so they handle events by delegation: a `data-action` attribute on the element, and a `kind:action` handler in the class's static `actions`. Redraw only the part that changed while someone types, or the input loses focus.
- **Card registration.** Define cards on `window.customElements` only after `customElements.whenDefined("home-assistant")`. The frontend swaps in its own registry as it boots and ignores cards defined before that.
- **New card.** Add its file to `SOURCES` in `scripts/build.js` (unless it joins an existing file) and its element name to `tests/cards/bundle.test.js`. Register it in `window.customCards` with `documentationURL` set to its README anchor, and give it a README section with screenshots.
- **Shared scope.** The bundle wraps each card script in its own block and loads as a module, so it is strict code. Never rely on a name from another script, and never declare globals except `window.customCards`.
- **Languages.** Each card has a `STRINGS` table in 11 languages: en, de, es, fr, it, nl, pl, pt, pt-BR, sv and zh-Hans. Add a key to `en` first, then to each language. The tests check keys and placeholders.
- **Theming.** Take colours and fonts from Home Assistant theme variables, never hard-coded colours.
- **People.** Each person is a config sub-entry. Code refers to a person by the `key` in its data, never by name or sub-entry ID. Re-adding a removed person under the same name reuses their key, which brings back their data, entities and history.
- **Writes.** Go through `FitnessData`, never `Database` directly. It runs the query in the executor, holds the lock that backups pause on, refreshes goals, corrects the recorder's statistics for past days, and sends `SIGNAL_CHANGED` to the sensors and the cards.
- **Both databases.** Every query must work on SQLite and Postgres: build it with SQLAlchemy Core, not raw SQL, and test it through `database_url`. Days are ISO date strings in both.
- **Schema.** `MIGRATIONS` in `db.py` upgrades a database one version at a time, and `schema_version` records where it is. Never edit a released migration or `_schema_v1`; add a new schema function and a migration to it.
- **Cleanup.** Tests create nothing outside temporary folders and the throwaway Postgres server, and remove both even when they fail.
- **Daily totals.** Use `state_class: total` with `last_reset` at local midnight, never `total_increasing`: deleting an entry lowers a total, which `total_increasing` would read as a meter reset.
- **Integration strings.** `translations/*.json` cover the same 11 languages as the cards. `tests/integration/test_translations.py` checks each matches `en.json`.
- **Open Food Facts.** Cards fetch it from the browser. Tests answer it with Playwright's `page.route`, never the real service.
- **App scanner.** `scanWithApp` wraps `hass.auth.external.receiveMessage`, which the frontend does not document. Keep calling the original handler, which acknowledges each message, and keep typing a barcode working without any scanner.
- **Coverage.** CI fails if the Python tests cover less than 90% of the integration's lines and branches (`fail_under` in `pyproject.toml`), and reports card unit coverage without enforcing it. Test new code anyway: card code needs a unit test for its pure functions and an end-to-end test for each interaction and failure path.
- **Frozen time.** The integration tests freeze time, so `asyncio.sleep` with a delay never returns there. Yield with `asyncio.sleep(0)`.

## Style

- Match the surrounding code. Comments say why, not what.
- The README is plain, short sentences.
- Commit subjects are short imperative sentences, with no type prefix.
