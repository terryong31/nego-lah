"""
Deciding whether `conversations` is safe to archive (SPEC-098).

The judgement is entirely about telling three states apart, and two of them look
identical to a row count:

* a **purged account** — `purge_user_data` deletes `messages` and `chat_settings`
  and has never touched `conversations`, so old history with no new history is
  the expected end state of someone deleting their account;
* a **live user with no messages** — same numbers, completely different meaning:
  their history exists only in the table we are about to put away;
* a **shrunken transcript** — present in both, but fewer rows than the old array
  held, which is what a half-finished backfill looks like.

`user_profiles` is what separates the first two, so the assessment takes it as
an input rather than guessing from counts.
"""

import pytest

from scripts.verify_conversations_retirement import (
    NEEDS_REVIEW,
    OK,
    PURGED,
    assess,
    exit_code,
)


def row(user_id="u1", old=0, new=0, profile=True):
    return {"user_id": user_id, "old_count": old, "new_count": new, "has_profile": profile}


class TestClassification:
    def test_a_purged_account_is_expected_not_a_problem(self):
        """Old history, no new history, no profile: they deleted their account."""
        report = assess([row(old=12, new=0, profile=False)])
        assert report.verdicts["u1"] == PURGED
        assert report.needs_review == []

    def test_a_live_user_with_no_messages_needs_review(self):
        """Same counts, but the account still exists — their history is only here."""
        report = assess([row(old=12, new=0, profile=True)])
        assert report.verdicts["u1"] == NEEDS_REVIEW
        assert "u1" in report.needs_review

    def test_a_shrunken_transcript_needs_review(self):
        """Present in both, but the backfill left some behind."""
        report = assess([row(old=40, new=12, profile=True)])
        assert report.verdicts["u1"] == NEEDS_REVIEW

    def test_more_messages_than_the_old_array_is_normal(self):
        """The cutover was two weeks ago; people kept talking."""
        report = assess([row(old=12, new=57, profile=True)])
        assert report.verdicts["u1"] == OK
        assert report.needs_review == []

    def test_an_exact_match_is_fine(self):
        assert assess([row(old=12, new=12)]).verdicts["u1"] == OK

    def test_an_empty_old_array_is_fine_either_way(self):
        """A conversations row that never held anything proves nothing."""
        assert assess([row(old=0, new=0, profile=True)]).verdicts["u1"] == OK
        assert assess([row(old=0, new=9, profile=True)]).verdicts["u1"] == OK

    def test_a_shrunken_transcript_for_a_purged_account_is_still_purged(self):
        """No profile means the rows went on purpose, whatever the numbers say."""
        assert assess([row(old=40, new=3, profile=False)]).verdicts["u1"] == PURGED


class TestReport:
    def test_an_empty_table_is_safe(self):
        report = assess([])
        assert report.needs_review == []
        assert report.total_users == 0
        assert exit_code(report) == 0

    def test_the_totals_are_summed_across_users(self):
        report = assess([row("a", old=10, new=10), row("b", old=5, new=6)])
        assert report.total_users == 2
        assert report.total_old_messages == 15

    def test_the_exit_code_is_non_zero_only_when_something_needs_review(self):
        clean = assess([row("a", old=1, new=2), row("b", old=3, new=0, profile=False)])
        assert exit_code(clean) == 0

        dirty = assess([row("a", old=1, new=2), row("b", old=3, new=0, profile=True)])
        assert exit_code(dirty) == 1

    def test_review_cases_are_listed_for_a_human_to_read(self):
        report = assess([row("a", old=9, new=0, profile=True), row("b", old=1, new=1)])
        assert report.needs_review == ["a"]
        assert report.counts[PURGED] == 0
        assert report.counts[OK] == 1
        assert report.counts[NEEDS_REVIEW] == 1


class TestMigrationArtifact:
    """The migration ships through CI (SPEC-096), so it must satisfy those rules."""

    MIGRATION = "20260920000000_retire_conversations_to_archive.sql"

    @pytest.fixture(scope="class")
    def sql(self):
        from scripts.validate_migrations import MIGRATIONS_DIR

        path = MIGRATIONS_DIR / self.MIGRATION
        assert path.exists(), f"{self.MIGRATION} not found"
        return path.read_text()

    def test_the_filename_passes_validation(self):
        from scripts.validate_migrations import duplicate_versions, invalid_names

        assert invalid_names([self.MIGRATION]) == []
        assert self.MIGRATION.split("_")[0] > "20260915000000", "must sort after the last migration"

        from scripts.validate_migrations import MIGRATIONS_DIR

        names = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
        assert duplicate_versions(names) == {}

    def test_nothing_is_destroyed(self, sql):
        lowered = sql.lower()
        assert "set schema archive" in lowered
        assert "drop table" not in lowered
        assert "delete from" not in lowered
        assert "truncate" not in lowered

    def test_it_guards_the_case_where_the_backfill_never_ran(self, sql):
        lowered = sql.lower()
        assert "raise exception" in lowered
        assert "public.messages" in lowered

    def test_it_documents_how_to_reverse_it(self, sql):
        assert "set schema public" in sql.lower(), "the reverse statement must be written down"
