---
id: SPEC-076
title: Clear User Chat Ops Script
status: complete
priority: medium
created: 2026-09-12
tags: [ops, scripts, supabase, chat]
assigned: agent
---

# Context & Objectives
Support/debugging on staging sometimes needs a user's conversation history
wiped (e.g. testing a fresh buyer journey for `terryong30@gmail.com`). Today
there is no repo tool for it — the only deletion path is an in-process
`conversation_memory.clear_history` call. Add a one-off ops script following
the established patterns (`unban_user.py` for auth lookup,
`backfill_custom_avatar.py` for dry-run/`--apply`), so the operation is
repeatable, auditable, and safe by default.

# Acceptance Criteria
- [x] `uv run python scripts/clear_user_chat.py <email>` resolves the account
      by email via the Supabase auth admin API (case-insensitive) and prints
      which project it is pointed at, the user id, and the message count.
- [x] Dry run is the default: no delete happens without `--apply`.
- [x] `--apply` deletes every `messages` row for that `user_id` and re-counts
      to verify zero remain.
- [x] Unknown email exits non-zero with guidance, deleting nothing.
- [x] Console chat list empties for the user (it derives from `messages`).

# Technical Design & Contracts
- Conversation history is the single `messages` table keyed by `user_id`
  (SPEC-043 shape); both the buyer chat and the admin console read it. No
  other table holds the transcript.
- Counting uses PostgREST `count=exact`; delete filters `eq("user_id", uid)`
  only — never a bare `delete()` with no filter.
- Env is whatever the caller injects (`infisical run --env=dev` for staging,
  `--env=prod` for production); the script prints `SUPABASE_URL` so the
  target project is always visible in the transcript.

# Test-Driven Development (TDD) Scenarios
- [x] Dry run: counts the user's messages, never calls `delete`.
- [x] `--apply`: calls the delete filtered by `user_id`, re-counts to 0.
- [x] Unknown email: exit code 1, no `delete` call.
- [x] Email match is case-insensitive.

# Implementation Files
- `backend/scripts/clear_user_chat.py` - the ops script
- `backend/tests/test_scripts_clear_user_chat.py` - guard tests
