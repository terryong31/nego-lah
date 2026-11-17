#!/usr/bin/env bash
# Frontend dependency vulnerability gate (audit SUP-1, 2026-10-06).
#
# Fails on any high or critical advisory. All previously ignored advisories
# (simple-git, braces, node-forge) have been resolved or upgraded out of the
# dependency tree.
set -euo pipefail
cd "$(dirname "$0")/.."
exec bun audit --audit-level=high
