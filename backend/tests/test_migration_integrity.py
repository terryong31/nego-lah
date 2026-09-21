"""
Migration integrity rules (SPEC-096).

`scripts/run_migrations.py` records the leading 14 digits of a filename as the
applied *version* and skips any version it has already seen. Two consequences
are correctness rules rather than style preferences:

* a duplicate version prefix means the second file is marked applied without
  ever being executed, and
* editing a migration that is already applied changes the repo and not the
  database — the two diverge silently, with no error anywhere.

CI enforces both before a push to `main` reaches the `migrate` job.
"""

import pytest

from scripts.validate_migrations import (
    MIGRATIONS_DIR,
    append_only_violations,
    duplicate_versions,
    invalid_names,
    validate_repository,
)


class TestFilenameConvention:
    def test_the_committed_migrations_all_conform(self):
        """The repository is the baseline: whatever ships today must pass."""
        names = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
        assert names, "no migrations found — the glob or the path is wrong"
        assert invalid_names(names) == []

    @pytest.mark.parametrize(
        "name",
        [
            "baseline.sql",  # no version prefix
            "2026_baseline_schema.sql",  # prefix too short
            "20260628000000_Baseline_Schema.sql",  # uppercase
            "20260628000000_baseline schema.sql",  # space
            "20260628000000_baseline_schema.SQL",  # wrong extension case
            "20260628000000baseline.sql",  # missing separator
        ],
    )
    def test_malformed_names_are_rejected(self, name):
        problems = invalid_names([name])
        assert problems, f"{name!r} should have been rejected"
        assert name in problems[0], "the offending filename must appear in the message"

    def test_a_well_formed_name_is_accepted(self):
        assert invalid_names(["20260628000000_baseline_schema.sql"]) == []


class TestVersionUniqueness:
    def test_duplicate_version_prefixes_are_reported_with_both_files(self):
        dupes = duplicate_versions(
            [
                "20260628000000_baseline_schema.sql",
                "20260628000000_rls_and_storage.sql",
                "20260629000000_item_soft_delete.sql",
            ]
        )
        assert "20260628000000" in dupes
        assert dupes["20260628000000"] == [
            "20260628000000_baseline_schema.sql",
            "20260628000000_rls_and_storage.sql",
        ]

    def test_distinct_versions_are_clean(self):
        assert duplicate_versions(["20260628000000_a.sql", "20260629000000_b.sql"]) == {}

    def test_the_committed_migrations_have_unique_versions(self):
        names = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
        assert duplicate_versions(names) == {}


class TestAppendOnly:
    """`git diff --name-status` lines: only additions may touch the directory."""

    def test_a_new_migration_is_allowed(self):
        assert append_only_violations(["A\tsupabase/migrations/20260918000000_new_thing.sql"]) == []

    def test_modifying_an_existing_migration_is_rejected(self):
        violations = append_only_violations(["M\tsupabase/migrations/20260628000000_baseline_schema.sql"])
        assert len(violations) == 1
        assert "20260628000000_baseline_schema.sql" in violations[0]

    def test_deleting_an_existing_migration_is_rejected(self):
        violations = append_only_violations(["D\tsupabase/migrations/20260628000000_baseline_schema.sql"])
        assert len(violations) == 1

    def test_renaming_an_existing_migration_is_rejected(self):
        violations = append_only_violations(
            ["R100\tsupabase/migrations/20260628000000_a.sql\tsupabase/migrations/20260628000000_b.sql"]
        )
        assert len(violations) == 1

    def test_changes_outside_the_migrations_directory_are_ignored(self):
        assert append_only_violations(["M\tbackend/main.py", "M\tsupabase/config.toml"]) == []

    def test_blank_and_malformed_lines_do_not_crash(self):
        assert append_only_violations(["", "   ", "garbage-without-a-tab"]) == []


class TestRepositoryValidation:
    def test_the_live_repository_passes(self):
        """The end-to-end entry point CI calls, run against the real directory."""
        assert validate_repository() == []


class TestCommandLineEntryPoint:
    """The exact surface `migrations-check` runs. Its exit code gates a PR."""

    def test_a_clean_repository_exits_zero(self, capsys):
        from scripts.validate_migrations import main

        assert main([]) == 0
        assert "valid" in capsys.readouterr().out

    def test_an_append_only_violation_on_stdin_exits_nonzero(self, capsys, monkeypatch):
        import io

        from scripts.validate_migrations import main

        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO("M\tsupabase/migrations/20260628000000_baseline_schema.sql\n"),
        )
        assert main(["--diff-from-stdin"]) == 1
        out = capsys.readouterr().out
        assert "20260628000000_baseline_schema.sql" in out
        assert "Add a new migration instead" in out

    def test_an_added_migration_on_stdin_exits_zero(self, monkeypatch):
        import io

        from scripts.validate_migrations import main

        monkeypatch.setattr("sys.stdin", io.StringIO("A\tsupabase/migrations/20260918000000_new.sql\n"))
        assert main(["--diff-from-stdin"]) == 0

    def test_a_missing_directory_is_reported_not_crashed(self, monkeypatch, tmp_path, capsys):
        from scripts import validate_migrations

        monkeypatch.setattr(validate_migrations, "MIGRATIONS_DIR", tmp_path / "nope")
        assert validate_migrations.main([]) == 1
        assert "not found" in capsys.readouterr().out

    def test_an_empty_directory_is_reported(self, monkeypatch, tmp_path, capsys):
        from scripts import validate_migrations

        monkeypatch.setattr(validate_migrations, "MIGRATIONS_DIR", tmp_path)
        assert validate_migrations.main([]) == 1
        assert "no .sql migrations" in capsys.readouterr().out
