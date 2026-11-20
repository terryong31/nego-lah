---
id: SPEC-115
title: Remove Archived langchain-community & Refresh LangChain Stack
status: complete
priority: medium
created: 2026-11-20
tags: [dependencies, security, backend, langchain]
assigned: agent
---

# Context & Objectives

- **Archived Dependency (`uv audit`):** Running `uv audit` in `backend/` flags `langchain-community` as an adverse project status (`langchain-community is archived`). Upstream archived `langchain-community` as read-only under LangChain v1 in favor of dedicated partner packages (`langchain-google-genai`, `langchain-openai`), `langchain-core`, `langgraph`, and direct wrappers (`ddgs`).
- **Unused Legacy Weight:** `backend/` has zero Python imports of `langchain_community` or `langchain_classic`. Keeping `langchain-community>=0.4.1` in `backend/pyproject.toml` pulls both `langchain-community` and `langchain-classic` (which emits sunset deprecation warnings during tests) into `backend/uv.lock` and the production container image for no reason.
- **Latest LangChain Packages:** Refresh the active LangChain stack (`langchain`, `langchain-core`, `langchain-google-genai`, `langchain-openai`, `langgraph`) in `backend/uv.lock` to their latest compatible releases.

# Acceptance Criteria

- [x] `langchain-community` is removed from `backend/pyproject.toml`.
- [x] Neither `langchain-community` nor `langchain-classic` appears in `backend/uv.lock` or the synced environment.
- [x] Active LangChain packages (`langchain`, `langchain-core`, `langchain-google-genai`, `langchain-openai`, `langgraph`) are upgraded to their latest compatible PyPI releases in `backend/uv.lock`.
- [x] `uv audit --preview-features audit-command` in `backend/` reports zero known vulnerabilities and zero adverse project statuses.
- [x] A regression test (`backend/tests/test_dependencies.py`) guards `pyproject.toml`, `uv.lock`, and backend Python imports against re-introducing `langchain-community` or `langchain-classic`.
- [x] Backend test suite (coverage ≥ 88%), `ruff`, `bandit`, `pip-audit`, and docs checks all pass.

# Technical Design & Contracts

- **Dependency Cleanup (`backend/pyproject.toml`, `backend/uv.lock`):**
  - Remove `"langchain-community>=0.4.1"` from `[project].dependencies`.
  - Upgrade `langchain`, `langchain-core`, `langchain-google-genai`, `langchain-openai`, and `langgraph` (and their lockfile-only LangChain siblings such as `langchain-protocol` and `langgraph-prebuilt`) via `uv lock --upgrade-package ...`.
- **Guardrail Contract (`backend/tests/test_dependencies.py`):**
  - Parses `backend/pyproject.toml` and `backend/uv.lock` with stdlib `tomllib`.
  - Asserts archived/retired packages (`langchain-community`, `langchain-classic`) are absent from declared dependencies, dependency groups, and resolved lockfile packages.
  - AST-scans every `.py` file under `backend/` (skipping `.venv`) and asserts no `import` or `from ... import` references `langchain_community` or `langchain_classic`.

# TDD Scenarios

- [x] **Declared dependency guard:** `test_no_archived_packages_in_pyproject` fails while `langchain-community` is in `backend/pyproject.toml` and passes once removed.
- [x] **Lockfile guard:** `test_no_archived_packages_in_uv_lock` fails while `langchain-community` or `langchain-classic` is resolved in `backend/uv.lock` and passes after re-locking.
- [x] **Import AST guard:** `test_no_archived_package_imports_in_backend` confirms zero backend modules import `langchain_community` or `langchain_classic`.
- [x] **Negotiation & full backend regression:** Existing `tests/test_agent_*.py` and full `uv run pytest` pass with upgraded LangChain packages and ≥ 88% coverage.

# Implementation Files

- `docs/specs/SPEC-115-remove-archived-langchain-community.md`
- `docs/specs/README.md`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/tests/test_dependencies.py`
