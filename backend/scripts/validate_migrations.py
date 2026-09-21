"""
Migration integrity checks for CI (SPEC-096).

`run_migrations.py` records the leading 14 digits of a filename as the applied
*version* and skips any version already present in
`supabase_migrations.schema_migrations`. Two rules fall out of that design, and
neither of them fails loudly on its own:

1. **Versions must be unique.** A duplicate prefix marks the second file applied
   the moment the first runs, so its SQL never executes.
2. **Merged migrations are immutable.** An applied version is never re-read, so
   editing one changes the repository and not the database. Nothing errors; the
   two simply disagree from then on.

Run with no arguments to validate the migration directory. Pass
`--diff-from-stdin` and feed it `git diff --name-status <base>...<head>` to also
enforce the append-only rule on a pull request.
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
MIGRATIONS_PREFIX = "supabase/migrations/"

# <14-digit version>_<lower_snake_name>.sql — the version is what gets recorded,
# so the shape of it is a correctness constraint, not a naming preference.
MIGRATION_NAME = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")

VERSION_LENGTH = 14


def invalid_names(names: list[str]) -> list[str]:
    """Filenames that do not match `YYYYMMDDHHMMSS_lower_snake_name.sql`."""
    return [
        f"{name!r} does not match the required <14-digit version>_<lower_snake_name>.sql form"
        for name in names
        if not MIGRATION_NAME.match(name)
    ]


def version_of(name: str) -> str:
    """The version string `run_migrations.py` will record for this file."""
    return name.split("_")[0]


def duplicate_versions(names: list[str]) -> dict[str, list[str]]:
    """Version prefixes claimed by more than one file, mapped to those files."""
    by_version: dict[str, list[str]] = defaultdict(list)
    for name in names:
        by_version[version_of(name)].append(name)
    return {version: sorted(files) for version, files in by_version.items() if len(files) > 1}


def append_only_violations(name_status_lines: list[str]) -> list[str]:
    """
    Changes to `supabase/migrations/` that are not plain additions.

    Takes `git diff --name-status` output: a status letter, a tab, then one path
    (two for a rename). Anything that is not an addition rewrites history the
    database has already applied.
    """
    violations = []
    for raw in name_status_lines:
        fields = raw.strip().split("\t")
        if len(fields) < 2:
            continue
        status, paths = fields[0], fields[1:]
        touched = [p for p in paths if p.startswith(MIGRATIONS_PREFIX)]
        if not touched or status.startswith("A"):
            continue
        verb = {"M": "modified", "D": "deleted", "R": "renamed", "C": "copied", "T": "retyped"}.get(
            status[0], f"changed ({status})"
        )
        violations.append(
            f"{touched[0]} was {verb} — a merged migration is already applied in production, "
            "so editing it changes the repository and not the database. Add a new migration instead."
        )
    return violations


def validate_repository() -> list[str]:
    """Every problem with the migration directory as it stands. Empty is good."""
    if not MIGRATIONS_DIR.is_dir():
        return [f"migrations directory not found at {MIGRATIONS_DIR}"]

    names = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    if not names:
        return [f"no .sql migrations found in {MIGRATIONS_DIR}"]

    problems = invalid_names(names)
    problems += [
        f"version {version} is claimed by {len(files)} files ({', '.join(files)}) — "
        "only the first would ever run"
        for version, files in sorted(duplicate_versions(names).items())
    ]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diff-from-stdin",
        action="store_true",
        help="also read `git diff --name-status` on stdin and enforce append-only",
    )
    args = parser.parse_args(argv)

    problems = validate_repository()
    if args.diff_from_stdin:
        problems += append_only_violations(sys.stdin.read().splitlines())

    if problems:
        print("Migration validation failed:\n")
        for problem in problems:
            print(f"  ✗ {problem}")
        return 1

    count = len(list(MIGRATIONS_DIR.glob("*.sql")))
    print(f"✅ {count} migrations valid: names conform, versions unique, history untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
