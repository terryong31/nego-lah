"""
CI/CD wiring assertions (SPEC-096).

Migrations are applied by the pipeline, so the pipeline's shape is a contract:
a migration must trigger CI, must never be applied from a pull request, and must
land before the backend that depends on it. Asserting that against the parsed
YAML beats reading it and hoping, because these are exactly the lines that get
edited by whoever is in a hurry.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "deploy.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.exists(), f"workflow not found at {WORKFLOW}"
    # PyYAML reads the unquoted `on:` key as the boolean True (YAML 1.1); the
    # triggers live under that key, so normalise it once here.
    data = yaml.safe_load(WORKFLOW.read_text())
    if True in data:
        data["on"] = data.pop(True)
    return data


@pytest.fixture(scope="module")
def jobs(workflow) -> dict:
    return workflow["jobs"]


class TestTriggers:
    def test_migration_changes_are_not_ignored(self, workflow):
        """`supabase/**` in paths-ignore meant a schema change ran no CI at all."""
        for event in ("push", "pull_request"):
            ignored = workflow["on"][event].get("paths-ignore", [])
            assert not any("supabase" in p for p in ignored), (
                f"{event}.paths-ignore still skips supabase — migrations would not trigger CI: {ignored}"
            )

    def test_both_events_still_target_main(self, workflow):
        for event in ("push", "pull_request"):
            assert workflow["on"][event]["branches"] == ["main"]


class TestChangeDetection:
    def test_a_migrations_output_exists(self, jobs):
        assert "migrations" in jobs["changes"]["outputs"]

    def test_the_filter_watches_the_migrations_directory(self, jobs):
        filters = next(s for s in jobs["changes"]["steps"] if s.get("id") == "filter")
        assert "supabase/migrations/**" in filters["with"]["filters"]


class TestMigrateJob:
    def test_the_job_exists(self, jobs):
        assert "migrate" in jobs

    def test_it_only_runs_on_a_push_to_main(self, jobs):
        condition = jobs["migrate"]["if"]
        assert "github.event_name == 'push'" in condition
        assert "github.ref == 'refs/heads/main'" in condition

    def test_it_is_gated_on_an_actual_migration_change(self, jobs):
        assert "needs.changes.outputs.migrations == 'true'" in jobs["migrate"]["if"]

    def test_it_waits_for_validation(self, jobs):
        assert "migrations-check" in jobs["migrate"]["needs"]

    def test_it_holds_its_own_concurrency_group(self, jobs):
        """Two pushes must never apply migrations to one database at once."""
        concurrency = jobs["migrate"]["concurrency"]
        assert concurrency["cancel-in-progress"] is False, "cancelling mid-migration is worse than queueing"
        assert "github.ref" not in str(concurrency["group"]), "the group must be global, not per-ref"

    def test_it_declares_the_production_environment(self, jobs):
        """So a required-reviewer rule can be added in repo settings later."""
        assert jobs["migrate"]["environment"] == "production"

    def test_it_runs_the_migration_runner(self, jobs):
        script = " ".join(str(s.get("run", "")) for s in jobs["migrate"]["steps"])
        assert "run_migrations.py" in script

    def test_it_sources_the_database_url_from_infisical_prod(self, jobs):
        script = " ".join(str(s.get("run", "")) for s in jobs["migrate"]["steps"])
        assert "infisical" in script and "--env=prod" in script


class TestValidationNeverTouchesProduction:
    def test_the_check_job_runs_for_pull_requests(self, jobs):
        assert "migrations-check" in jobs
        assert "github.event_name == 'push'" not in jobs["migrations-check"].get("if", "")

    def test_the_check_job_holds_no_production_credential(self, jobs):
        """A PR from a fork must not be able to reach the production database."""
        rendered = yaml.safe_dump(jobs["migrations-check"])
        for secret in ("INFISICAL_TOKEN", "DATABASE_URL", "infisical"):
            assert secret not in rendered, f"validation job references {secret} — it must not"

    def test_the_check_job_validates_and_enforces_append_only(self, jobs):
        script = " ".join(str(s.get("run", "")) for s in jobs["migrations-check"]["steps"])
        assert "validate_migrations.py" in script
        assert "--diff-from-stdin" in script


class TestDeployOrdering:
    def test_backend_deploy_waits_for_migrate(self, jobs):
        assert "migrate" in jobs["deploy-backend"]["needs"]

    def test_a_failed_migration_blocks_the_deploy(self, jobs):
        condition = jobs["deploy-backend"]["if"]
        assert "needs.migrate.result != 'failure'" in condition
        assert "needs.migrate.result != 'cancelled'" in condition

    def test_a_skipped_migration_does_not_block_the_deploy(self, jobs):
        """Most pushes change no schema; `migrate` is skipped and must not gate."""
        condition = jobs["deploy-backend"]["if"]
        assert "always()" in condition, "without always(), a skipped need skips the deploy too"
        assert "needs.build-backend.result == 'success'" in condition, (
            "always() defeats implicit success checks — build-backend must be asserted explicitly"
        )


class TestHardening:
    """Audit DEP-1 / DEP-2 / SUP-1."""

    def test_the_default_token_is_read_only(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}

    def test_third_party_actions_are_pinned_by_sha(self, jobs):
        first_party = ("actions/", "docker/", "oven-sh/", "astral-sh/")
        for name, job in jobs.items():
            for step in job.get("steps", []):
                uses = step.get("uses")
                if not uses or uses.startswith(first_party):
                    continue
                ref = uses.split("@", 1)[1]
                assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), f"{name}: {uses}"

    def test_backend_ci_runs_bandit(self, jobs):
        assert any("bandit" in step.get("run", "") for step in jobs["backend-ci"]["steps"])

    def test_frontend_lint_runs_a_real_vulnerability_audit(self, jobs):
        runs = " ".join(step.get("run", "") for step in jobs["frontend-lint"]["steps"])
        assert "scripts/audit.sh" in runs
        script = (WORKFLOW.parent.parent.parent / "frontend" / "scripts" / "audit.sh").read_text()
        assert "bun audit --audit-level=high" in script
        assert "bun pm untrusted" not in runs

    def test_the_deploy_pins_the_commit_sha_and_waits_for_health(self, jobs):
        step = next(s for s in jobs["deploy-backend"]["steps"] if "restart on server" in s.get("name", ""))
        assert step["env"]["IMAGE_TAG"] == "${{ github.sha }}"
        script = step["with"]["script"]
        assert 'env BACKEND_IMAGE_TAG="$IMAGE_TAG" docker compose up' in script
        assert "Health.Status" in script
        assert "rollback" in script
        assert "docker compose restart caddy\n" not in script.replace("|| sudo docker compose restart caddy", "")
