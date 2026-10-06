# Contributing

Nego-Lah is a single-maintainer project. The source is public to read, but it is **not open
source**: the [licence](LICENSE) reserves all rights. Bug reports and security reports are welcome;
pull requests from outside are accepted only by prior agreement, so open an issue first.

## Reporting

- **Bugs and ideas:** open an [issue](https://github.com/terryong31/nego-lah/issues/new/choose).
- **Security vulnerabilities:** never in a public issue. Follow [SECURITY.md](SECURITY.md).

## Making a change

The full rules, written for people and coding agents alike, are in [AGENTS.md](AGENTS.md). In short:

1. **Spec first.** Any non-trivial change starts as a spec in `docs/specs/` from the
   [template](docs/specs/TEMPLATE.md). A hard-to-reverse architectural choice also gets an
   [ADR](docs/adr/README.md).
2. **Test first.** Write the failing test, then the code. Backend coverage must stay at or above 88%.
3. **Respect the boundaries.** Domains import only downward
   (`identity < catalog < billing < negotiation`); `backend/tests/test_domain_boundaries.py`
   enforces it.
4. **Update the docs in the same PR.** If behaviour changes, change the living doc that
   describes it ([docs/README.md](docs/README.md)). Run `mise run docs:openapi` after a route
   change and `mise run docs:index` after adding a spec or ADR.
5. **Check locally:** `mise run lint`, `mise run test`, `mise run docs:lint`, `mise run docs:prose`.
   The pre-push hook runs the tests for you. `mise run docs:stale` lists docs your change may have
   made stale.

Setup: [Getting started](docs/tutorials/getting-started.md).

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) with a scope:
`fix(api): …`, `feat(web): …`, `docs: …`. Reference the spec, e.g. `(SPEC-102)`.

## Conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
