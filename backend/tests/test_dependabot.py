"""
Dependency-update wiring (SPEC-103).

A Renovate config sat in `frontend/` for months where Renovate never looks, and
the audit read its presence as "configured". The bot config is a contract: one
bot, every ecosystem the repo ships, and no stray config that looks like a second.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = REPO_ROOT / ".github" / "dependabot.yml"

EXPECTED = {
    ("bun", "/frontend"),
    ("uv", "/backend"),
    ("github-actions", "/"),
    ("docker", "/frontend"),
    ("docker", "/backend"),
    ("docker-compose", "/"),
}


@pytest.fixture(scope="module")
def updates() -> list[dict]:
    assert CONFIG.exists(), f"dependabot config not found at {CONFIG}"
    data = yaml.safe_load(CONFIG.read_text())
    assert data["version"] == 2
    return data["updates"]


def test_config_uses_no_yaml_aliases():
    """Dependabot's parser rejects anchors/aliases ("YAML aliases are not supported")."""
    events = yaml.parse(CONFIG.read_text())
    aliased = [e for e in events if isinstance(e, yaml.AliasEvent) or getattr(e, "anchor", None)]
    assert not aliased, "inline every repeated block; Dependabot cannot resolve YAML aliases"


def test_no_renovate_config_remains():
    skip = {"node_modules", ".git", ".venv", ".nuxt", ".output"}
    found = [
        p.relative_to(REPO_ROOT)
        for pattern in ("renovate.json*", ".renovaterc*")
        for p in REPO_ROOT.rglob(pattern)
        if not skip & set(p.parts)
    ]
    assert not found, f"Dependabot owns updates; remove Renovate config: {found}"


def test_every_ecosystem_is_covered_exactly_once(updates):
    pairs = [(u["package-ecosystem"], u["directory"]) for u in updates]
    assert len(pairs) == len(set(pairs)), f"duplicate update entries: {pairs}"
    assert set(pairs) == EXPECTED


@pytest.mark.parametrize("field", ["schedule", "open-pull-requests-limit", "groups"])
def test_every_entry_is_weekly_capped_and_grouped(updates, field):
    for u in updates:
        assert field in u, f"{u['package-ecosystem']} {u['directory']} has no {field}"
        if field == "schedule":
            assert u["schedule"]["interval"] == "weekly"
        if field == "groups":
            types = {t for g in u["groups"].values() for t in g.get("update-types", [])}
            assert {"minor", "patch"} <= types and "major" not in types
