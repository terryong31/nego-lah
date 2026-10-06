"""
SPEC-102 — docs are checked like code.

The living docs had drifted to describe directories, auth and endpoints that no
longer existed, and nothing went red. These checks cover the drift a machine can
see: a committed API contract that disagrees with the app, a link to a file that
moved, an index that forgot a spec, an ADR with no status. Prose accuracy is
still a reviewer's job; these make sure the reviewer is not also the link checker.
"""

import json
import re

import pytest

from scripts import docs_tools
from scripts.docs_tools import (
    ADR_DIR,
    OPENAPI_PATH,
    REPO_ROOT,
    SPECS_DIR,
    adr_metadata,
    generated_region,
    openapi_document,
    render_adr_index,
    render_spec_index,
)

LINK = re.compile(r"\]\(([^)\s]+)\)")


def _doc_files():
    yield from sorted((REPO_ROOT / "docs").rglob("*.md"))
    for name in ("README.md", "AGENTS.md", "SECURITY.md", "backend/AGENTS.md"):
        path = REPO_ROOT / name
        if path.exists():
            yield path


def _broken_links(path):
    text = path.read_text()
    # Links inside code are examples, not navigation.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    for target in LINK.findall(text):
        target = target.split("#", 1)[0]
        if not target or re.match(r"^[a-z]+:", target):
            continue
        if not (path.parent / target).resolve().exists():
            yield target


def test_every_relative_link_resolves():
    broken = [(str(p.relative_to(REPO_ROOT)), t) for p in _doc_files() for t in _broken_links(p)]
    assert not broken, f"broken doc links: {broken}"


def test_broken_link_is_detected(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("[ok](a.md) [gone](missing.md) [web](https://x.y) `[inline](nope.md)` ```\n[code](nope.md)\n```")
    assert list(_broken_links(doc)) == ["missing.md"]


def test_committed_openapi_matches_the_app():
    committed = json.loads(OPENAPI_PATH.read_text())
    live = openapi_document()
    added = sorted(set(live["paths"]) - set(committed["paths"]))
    removed = sorted(set(committed["paths"]) - set(live["paths"]))
    assert committed == live, (
        f"docs/api/openapi.json is stale (added {added}, removed {removed}). Run `mise run docs:openapi`."
    )


def test_spec_index_is_current():
    readme = (SPECS_DIR / "README.md").read_text()
    assert generated_region(readme) == render_spec_index(), "specs index is stale. Run `mise run docs:index`."


def test_adr_index_is_current():
    readme = (ADR_DIR / "README.md").read_text()
    assert generated_region(readme) == render_adr_index(), "ADR index is stale. Run `mise run docs:index`."


@pytest.mark.parametrize("path", sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")), ids=lambda p: p.name[:4])
def test_every_adr_opens_with_status_and_date(path):
    meta = adr_metadata(path)
    assert re.fullmatch(r"Proposed|Accepted|Rejected|Deprecated|Superseded by ADR-\d{4}", meta["status"]), meta
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["date"]), meta
    assert meta["title"], meta


def test_adr_without_status_is_rejected(tmp_path):
    adr = tmp_path / "0099-x.md"
    adr.write_text("# ADR-0099: X\n\n- Date: 2026-10-07\n")
    with pytest.raises(ValueError):
        adr_metadata(adr)


def test_replace_generated_region_keeps_the_surrounding_prose():
    before = f"intro\n{docs_tools.BEGIN}\nold\n{docs_tools.END}\noutro\n"
    after = docs_tools.replace_generated_region(before, "new\n")
    assert after == f"intro\n{docs_tools.BEGIN}\nnew\n{docs_tools.END}\noutro\n"


# --- Staleness (SPEC-102) ---------------------------------------------------
# A living doc is suspect when the code it describes changed after it did. This
# is a nudge for the reviewer, not a gate: code can change without the doc
# needing to.


def test_every_living_doc_names_code_that_exists():
    for doc, globs in docs_tools.LIVING_DOCS.items():
        assert (REPO_ROOT / doc).exists(), doc
        for pattern in globs:
            assert list(REPO_ROOT.glob(pattern)), f"{doc}: '{pattern}' matches nothing"


def test_a_doc_older_than_its_code_is_flagged():
    stale = docs_tools.stale_docs({"doc.md": 100, "code.py": 200}, {"doc.md": ["code.py"]})
    assert stale == [("doc.md", "code.py")]


def test_a_doc_newer_than_its_code_is_not_flagged():
    assert docs_tools.stale_docs({"doc.md": 300, "code.py": 200}, {"doc.md": ["code.py"]}) == []


def test_the_report_names_each_stale_doc(monkeypatch, capsys):
    monkeypatch.setattr(docs_tools, "_last_change", lambda p: 1 if p.startswith("docs/") else 2)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    docs_tools.report_stale()
    out = capsys.readouterr().out
    assert all(doc in out for doc in docs_tools.LIVING_DOCS)


def test_last_change_reads_git(monkeypatch):
    assert docs_tools._last_change("docs/README.md") > 0
