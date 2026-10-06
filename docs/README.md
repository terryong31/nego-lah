# Nego-Lah Documentation

Nego-Lah is a second-hand marketplace where an AI agent negotiates the price with each buyer.
This folder is the engineering documentation. The [project README](../README.md) has the pitch
and the quickstart.

## Start here

| You want to… | Read |
|--------------|------|
| Run it locally and see it work | [Getting started tutorial](tutorials/getting-started.md) |
| Understand how it fits together | [Architecture](architecture/README.md), then [Agent architecture](architecture/agent.md) |
| Call the API | [API reference](api/README.md) and [`openapi.json`](api/openapi.json) |
| Change the schema | [Data model](data/README.md), then [Apply a database migration](how-to/apply-a-database-migration.md) |
| Ship or roll back | [Deploy and roll back](how-to/deploy-and-roll-back.md), [CI/CD](ci-cd/README.md) |
| Know why something is the way it is | [Architecture decision records](adr/README.md) |
| Build a feature | [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`AGENTS.md`](../AGENTS.md), then [Specs](specs/README.md) |
| Report a vulnerability | [`SECURITY.md`](../SECURITY.md) |

## Living docs

These describe the system **as it is now**. A PR that changes behaviour updates the page that
describes it.

| Page | Kind | Covers |
|------|------|--------|
| [Architecture](architecture/README.md) | Explanation | Components, backend layers and domain rules, constraints. |
| [Agent architecture](architecture/agent.md) | Explanation | Model routing, turn shapes, tools, server-enforced pricing rules. |
| [Core flows](flows/README.md) | Explanation | Sequence diagrams: negotiation turn, payment and fulfilment, human hand-over. |
| [Data model](data/README.md) | Reference | Tables, ownership, confidential columns, Redis keys, storage. |
| [API reference](api/README.md) | Reference | Authentication, route groups; [`openapi.json`](api/openapi.json) is generated. |
| [Background work](workers/README.md) | Reference | In-process loops, detached turns, shutdown. |
| [CI/CD](ci-cd/README.md) | Reference | Pipeline, deploy targets, quality and security gates. |
| [Repository guide](repo/README.md) | Reference | Layout, toolchain, everyday tasks. |
| [Security anti-patterns](security/ANTI_PATTERNS.md) | Reference | Vulnerabilities found here before, and the rules that prevent them. |
| [Getting started](tutorials/getting-started.md) | Tutorial | Run it locally, list an item, haggle for it. |
| [How-to guides](how-to/README.md) | How-to | Migrations, deploys, admin access, email diagnosis. |

## Records

These are **point-in-time**. They explain a decision or a change as it was made and are not
updated when the system moves on; a later record supersedes them instead.

| Record | What it is |
|--------|-----------|
| [ADRs](adr/README.md) | One significant architectural decision each, with context and consequences. |
| [Specs](specs/README.md) | The contract for one change: acceptance criteria, design, tests. [SPEC-000](specs/SPEC-000-system-architecture.md) is the original blueprint. |
| [Audits](audits/) | Findings from a review at a date: [non-functional, 2026-10-06](audits/2026-10-06-non-functional-audit.md); [documentation, 2026-10-07](audits/2026-10-07-documentation-audit.md). |

## How the docs stay correct

| Check | Fails when | Fix |
|-------|-----------|-----|
| `backend/tests/test_docs.py` | a relative link is broken | fix the link |
| 〃 | `api/openapi.json` differs from the app | `mise run docs:openapi` |
| 〃 | the spec or ADR index is stale, or an ADR lacks `Status`/`Date` | `mise run docs:index` |
| `backend/tests/test_spec_registry.py` | a spec number repeats, its status is not in the vocabulary, or a `complete` spec has an unticked box | edit the frontmatter or the criteria |
| `markdownlint-cli2` (`mise run docs:lint`) | a living doc breaks Markdown structure rules | fix the Markdown |
| Vale (`mise run docs:prose`) | a product name is misspelled (error); marketing or condescending wording appears (warning) | reword; style in `.vale/styles/NegoLah` |
| `docs_tools stale` (`mise run docs:stale`) | never fails: lists living docs older than the code they describe | re-read the doc against the code |
| Playwright (`mise run test:e2e`) | the deployed API or SPA breaks a contract (sessions, OAuth callback, floor-price exposure) | see `frontend/e2e/` |

These are part of the backend suite, so they run on every `git push` through the lefthook
pre-push hook and in CI: with the backend suite when `backend/` changes, and in the `docs-check`
job when only docs change. A docs-only change never deploys anything. The checks catch mechanical
drift; whether the prose is still true is the reviewer's job.

## Writing style

- Write for an engineer who is new to the codebase. Lead with what the reader needs, then why.
- Name real files, settings and numbers, and link the ADR or spec behind a rule.
- Prefer one accurate table to three paragraphs. Do not paste code that will drift; point to it.
- No claim the code does not back up. If a number came from a measurement, say which.
