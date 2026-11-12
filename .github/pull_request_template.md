<!--
Thank you for the pull request. Please read CONTRIBUTING.md first: a feature,
an addition, or a change to how something works or looks needs an approved
issue, and a change people can see is shown in that issue before it is built.
-->

## What and why

<!-- What does this change, and why? -->

Closes #

## Things done

- [ ] It does what the approved issue, or the bug report, describes, and nothing else
- [ ] Unit tests for new or changed card functions, in `tests/cards/`
- [ ] Integration tests, on SQLite and Postgres, that check every line added or changed
- [ ] End-to-end tests in a laptop browser for every flow it adds or changes, failure paths included
- [ ] New strings in all 11 languages
- [ ] The README and its screenshots updated for what people see or set
- [ ] The cards bundle rebuilt (`node scripts/build.js`), and `ruff check . && ruff format --check .` pass
- [ ] I read [CONTRIBUTING.md](https://github.com/matteo-pacini/metron/blob/master/CONTRIBUTING.md)

## Where the tests ran

<!-- For example: "Linux, in the Nix dev shell: pytest --cov, the card tests, scripts/e2e". Say what you could not run, such as the Android app tests. -->
