# Contributing to Metron

Thank you for wanting to help. Metron has one maintainer, who reviews and merges every change, so a few rules keep it coherent and the reviews short.

## Before you write code

- **Bugs.** Open a [bug report](https://github.com/matteo-pacini/metron/issues/new?template=bug_report.yml). A fix for something that is plainly a bug can go straight to a pull request that links the report.
- **Small fixes.** Typos, wrong words in the README, and translation corrections can go straight to a pull request. A [translation issue](https://github.com/matteo-pacini/metron/issues/new?template=translation.yml) is welcome too.
- **Everything else.** A feature, an addition, or a change to how something works or looks starts as an [idea](https://github.com/matteo-pacini/metron/issues/new?template=feature_request.yml). Discuss it there, and wait until the maintainer gives it the `approved` label before you start: it means the change is wanted, and a pull request for it is welcome. A pull request for a change that was not approved may be closed, however good it is. [Approved ideas nobody has taken yet](https://github.com/matteo-pacini/metron/issues?q=is%3Aopen+label%3Aapproved+no%3Aassignee) are a good place to start.

## Changes people can see

Before you build a change people can see, show it in its issue: how each card it touches looks before and after, and the steps of each flow it changes, including what happens when something goes wrong. Screenshots, a sketch or a mock-up all do, as long as it is clear. The maintainer keeps the cards' design system up to date, and brings the change into it after merging.

If you like, the kit in `design/drafts/` builds an animated draft from the cards' own code; start from `example.js`. Zip the page it writes and drag the zip into the issue, as GitHub does not take HTML files.

## Tests

Every change comes with its tests, in the same pull request:

- **Cards:** unit tests for their pure functions, in `tests/cards/`.
- **The integration:** integration tests, which run on both SQLite and Postgres. CI fails below 90% of lines and branches. Every line you add or change needs a test that checks what it does, not only one that runs it.
- **Flows:** an end-to-end test in a laptop browser for every flow the change adds or changes, with its failure paths, not only the happy path. A flow written as a function in `FLOWS`, in `tests/e2e/flows.py`, runs on a laptop, on a phone and in the Home Assistant app; add a phone-only check where the phone behaves differently.
- **Strings:** every new string in all 11 languages, for the cards and the integration. If you are unsure of a translation, say which in the pull request.
- **Screenshots:** retake them with `scripts/screenshots` when the cards look different.

The end-to-end tests (`scripts/e2e`), the screenshots and the draft kit's check run on Linux only; elsewhere, they skip, and CI runs them on every pull request. The tests in the Home Assistant app on Android (`scripts/android-vm`) need nested KVM: if you cannot run them, say so in the pull request, and the maintainer will.

[AGENTS.md](AGENTS.md) has the layout, the commands, and the rules that are easy to break. Read it before you start.

## Pull requests

- One change per pull request, linked to its issue with `Closes #123`. Open it as a draft until it is ready for review.
- Fill in the template, and tick only what you did.
- The pull request's title becomes the commit's subject, as the maintainer squashes each pull request into one commit: a short imperative sentence, in plain words, with no prefix such as `feat:`.
- Every check must pass, and the maintainer must approve the pull request, before it can be merged. On your first pull request, CI starts once the maintainer lets it run.
- Answer a review with new commits rather than a force-push, so the review can follow what changed.
- A pull request with no reply for four weeks may be closed. It can be opened again at any time.

## Security

Report a security problem privately, with "Report a vulnerability" on the repository's [Security](https://github.com/matteo-pacini/metron/security) tab, never in an issue.

## Licence

Metron is licensed under the GNU Affero General Public License, version 3 or any later version. By contributing, you agree that your contribution is licensed under the same terms.
