# AGENTS.md

ZPMyFitnessCards is a Home Assistant custom integration, `zp_my_fitness`, with dashboard cards. HACS installs it as an integration, and the integration serves the cards' JavaScript itself.

## Layout

- `custom_components/zp_my_fitness/`: the integration. `brand/` holds its icons.
  - `db.py`: the SQLite database, with blocking methods. `data.py` (`FitnessData`) is the only caller.
  - `goals.py`: calorie, macro and BMI maths, with no Home Assistant code.
  - `coordinator.py` and `sensor.py`: each person's sensors, refreshed on every change and at midnight.
  - `websocket.py`: the commands the cards call.
  - `config_flow.py`: the integration and its people, one config sub-entry each.
  - `backup.py`: pauses writes while Home Assistant backs up.
- `custom_components/zp_my_fitness/frontend/zp-my-fitness-cards.js`: generated from `src/` by `scripts/build.js`. Never edit it by hand. Commit it rebuilt, together with every change to `src/`.
- `src/`: one plain browser script per card. There are no imports and no npm dependencies.
- `tests/integration/`: pytest with `pytest-homeassistant-custom-component`, in a test instance of Home Assistant.
- `tests/cards/`: Node's built-in test runner. `harness.js` loads a card script into a `vm` context with a stubbed DOM.
- `tests/e2e/`: pytest and Playwright against a brand-new Home Assistant, started from `.venv`, onboarded and set up by `conftest.py`.

## Commands

Work inside the Nix dev shell: `nix develop`, or direnv with `.envrc`. Entering it runs `uv sync`, which creates `.venv`.

```sh
node scripts/build.js                                    # rebuild the cards' bundle
node scripts/build.js --check                            # CI: fail if it is stale
node --experimental-vm-modules --test 'tests/cards/*.test.js'
pytest                                                   # integration tests
scripts/e2e                                              # end-to-end tests (Linux)
ruff check . && ruff format --check .
```

CI runs all of these through `nix develop -c`, plus hassfest and the HACS validator.

## Rules that are easy to break

- **Versions move together.** `pytest-homeassistant-custom-component` pins one Home Assistant release. The e2e packages in `pyproject.toml`, `home-assistant-frontend` and the rest, are pinned to what that release's manifests ask for. Playwright for Python must equal the Nix shell's `playwright-driver`; the e2e tests check it.
- **Schemas.** Import `vol` from `schema.py`, never `voluptuous` or `probatio` directly. Newer Home Assistant releases only accept probatio schemas and older ones only voluptuous, and the integration supports both (`hacs.json` sets the minimum).
- **Card registration.** Define cards on `window.customElements` only after `customElements.whenDefined("home-assistant")`. The frontend swaps in its own registry as it boots and ignores cards defined before that.
- **New card.** Add its file to `SOURCES` in `scripts/build.js` and its element name to `tests/cards/bundle.test.js`. Register it in `window.customCards` with `documentationURL` set to its README anchor.
- **Shared scope.** The bundle wraps each card script in its own block and loads as a module, so it is strict code. Never rely on a name from another script, and never declare globals except `window.customCards`.
- **Languages.** Each card has a `STRINGS` table in 11 languages: en, de, es, fr, it, nl, pl, pt, pt-BR, sv and zh-Hans. Add a key to `en` first, then to each language. The tests check keys and placeholders.
- **Theming.** Take colours and fonts from Home Assistant theme variables, never hard-coded colours.
- **People.** Each person is a config sub-entry. Code refers to a person by the `key` in its data, never by name or sub-entry ID. Re-adding a removed person under the same name reuses their key, which brings back their data, entities and history.
- **Writes.** Go through `FitnessData`, never `Database` directly. It runs the query in the executor, holds the lock that backups pause on, refreshes goals, corrects the recorder's statistics for past days, and sends `SIGNAL_CHANGED` to the sensors and the cards.
- **Schema.** `MIGRATIONS` in `db.py` upgrades a database one version at a time. Never edit a released migration; append a new one.
- **Daily totals.** Use `state_class: total` with `last_reset` at local midnight, never `total_increasing`: deleting an entry lowers a total, which `total_increasing` would read as a meter reset.
- **Integration strings.** `translations/*.json` cover the same 11 languages as the cards. `tests/integration/test_translations.py` checks each matches `en.json`.
- **Frozen time.** The integration tests freeze time, so `asyncio.sleep` with a delay never returns there. Yield with `asyncio.sleep(0)`.

## Style

- Match the surrounding code. Comments say why, not what.
- The README is plain, short sentences.
- Commit subjects are short imperative sentences, with no type prefix.
