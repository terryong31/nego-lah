#!/usr/bin/env bash
# Frontend dependency vulnerability gate (audit SUP-1, 2026-10-06).
#
# Fails on any high or critical advisory EXCEPT the ones below, each of which
# has no fixed release that this tree can take today, and none of which ships
# to a browser. Re-check them whenever this list is touched: delete a line the
# moment `bun audit` stops reporting it.
#
#   simple-git / @simple-git/argv-parser — pulled in by @nuxt/devtools 3.x; the
#     fix is simple-git 4, which only devtools 4 (beta) accepts. Devtools is
#     opt-in (NUXT_DEVTOOLS=true) since the same audit, so it does not run by
#     default on any machine.
#   braces <= 3.0.3 — no patched release exists; build-time globbing only.
#   node-forge <= 1.4.0 — no patched release exists; the `nuxt dev` HTTPS
#     helper (listhen) only.
set -euo pipefail
cd "$(dirname "$0")/.."
exec bun audit --audit-level=high \
  --ignore=GHSA-x6jw-m9v5-85vh \
  --ignore=GHSA-g4wm-2vf7-vfgr \
  --ignore=GHSA-858h-whjf-mvg5 \
  --ignore=GHSA-v5rq-49vh-5v5c \
  --ignore=GHSA-vfj7-8cjw-p6xm \
  --ignore=GHSA-86w9-cpqp-85rv
