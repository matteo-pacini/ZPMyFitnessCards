# ZPMyFitnessCards

A food diary and weight tracking for everyone in your home, inside Home Assistant.

ZPMyFitnessCards is a Home Assistant integration with its own dashboard cards. The plan: you log each food you eat by weight and meal, and your weight once a day. The integration keeps every entry in an SQLite database in your configuration folder, and exposes daily calories, macros and weight as sensors.

It is in early development. Today it sets up people and shows the first card. Logging food and weight comes next.

## Install

1. In HACS, add `https://github.com/matteo-pacini/ZPMyFitnessCards` as a custom repository of type Integration, then download ZPMyFitnessCards.
2. Restart Home Assistant.
3. In **Settings > Devices & services**, add **ZPMyFitnessCards**.
4. On its page, use **Add person** for each person.

The integration loads the cards for you. There is no dashboard resource to add.

Requires Home Assistant 2025.3 or later.

## Cards

### Food diary card

```yaml
type: custom:zp-food-diary-card
person: Debora
```

| Option | Description |
| --- | --- |
| `person` | Required. The name of a person added to the integration. |
| `locale` | Optional. A language code such as `it` or `pt-BR`. Defaults to Home Assistant's language. |

## Development

See [AGENTS.md](AGENTS.md) for the layout and commands. Everything runs in the Nix dev shell:

```sh
nix develop
pytest && scripts/e2e
```

## Licence

GNU Affero General Public License, version 3 or any later version (AGPL-3.0-or-later). See [LICENSE](LICENSE).
