---
id: SPEC-103
title: Dependabot Owns Dependency Updates
status: complete
priority: medium
created: 2026-10-07
tags: [ci, security, repo]
assigned: agent
---

# Context & Objectives
The [2026-10-06 audit](../audits/2026-10-06-non-functional-audit.md) said "Renovate is configured,
yet these versions are still behind." Nothing ran it: the only config was `frontend/renovate.json`,
a Nuxt-template leftover in a directory Renovate never reads, written for pnpm, and the Renovate
app was never installed. Dependabot had no config and its alerts were off. Nothing proposed an
upgrade. Pick one bot — Dependabot, since it needs no third-party app — and make it cover every
ecosystem the repo ships.

# Acceptance Criteria
- [x] `frontend/renovate.json` is deleted; no Renovate config remains.
- [x] `.github/dependabot.yml` covers `bun` (`/frontend`), `uv` (`/backend`), `github-actions`,
      `docker` (both Dockerfiles) and `docker-compose` (`/`).
- [x] Updates are weekly and grouped: minor+patch in one PR per ecosystem, majors one PR each.
- [x] Each ecosystem caps open PRs so a backlog cannot flood the queue.
- [x] Dependabot alerts and security updates are enabled in the repo settings.

# Technical Design & Contracts
- Schedule: weekly, Monday 09:00 `Asia/Kuala_Lumpur`.
- Commit prefixes `deps(web)`, `deps(api)`, `deps(ci)`, `deps(docker)` match the repo's scopes.
- SHA-pinned actions keep working: Dependabot bumps the SHA and its `# vX` comment together.
- Security updates are not grouped and ignore the PR cap, so a CVE fix is never held back.
- `mise.toml` tool versions are not covered; Dependabot has no mise ecosystem.

# TDD Scenarios
- [x] No `renovate.json` / `.renovaterc*` exists anywhere in the repo (`test_dependabot.py`).
- [x] Every expected `(ecosystem, directory)` pair is configured exactly once.
- [x] Every update entry has a weekly schedule, an open-PR limit and a minor/patch group.

# Implementation Files
- `.github/dependabot.yml`, `frontend/renovate.json` (deleted)
- `backend/tests/test_dependabot.py`, `docs/ci-cd/README.md`
