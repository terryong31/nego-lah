"""
SPEC-037 — spec numbers are identifiers, so they have to be unique.

LeanSpec's third principle is traceability: a spec number is how a commit, an
ADR or another spec points at a decision. Three numbers (017, 018, 024) had each
been used twice, so "see SPEC-018" named two different documents and resolved to
whichever one the reader happened to open. Nothing in the build noticed. This
does.
"""

import pathlib
import re

SPECS_DIR = pathlib.Path(__file__).resolve().parents[2] / "docs" / "specs"

SPEC_FILES = sorted(p for p in SPECS_DIR.glob("SPEC-*.md"))


def _frontmatter_id(path: pathlib.Path) -> str | None:
    match = re.search(r"^id:\s*(\S+)\s*$", path.read_text(), re.M)
    return match.group(1) if match else None


def test_specs_directory_is_not_empty():
    assert SPEC_FILES, "no specs found — is the path right?"


def test_spec_numbers_are_unique():
    seen: dict[str, list[str]] = {}
    for path in SPEC_FILES:
        number = path.name.split("-")[1]
        seen.setdefault(number, []).append(path.name)

    duplicates = {n: files for n, files in seen.items() if len(files) > 1}
    assert not duplicates, f"duplicate spec numbers: {duplicates}"


def test_frontmatter_id_matches_the_filename():
    """A renumbered file whose frontmatter still says the old id is the same
    ambiguity in a different place."""
    mismatched = []
    for path in SPEC_FILES:
        expected = f"SPEC-{path.name.split('-')[1]}"
        actual = _frontmatter_id(path)
        if actual != expected:
            mismatched.append((path.name, actual, expected))

    assert not mismatched, f"frontmatter id != filename: {mismatched}"


def test_every_spec_declares_an_id():
    missing = [p.name for p in SPEC_FILES if _frontmatter_id(p) is None]
    assert not missing, f"specs with no `id:` in frontmatter: {missing}"


# SPEC-102 — the status is how the index and a reader tell live work from history.
# Five spellings ("complete", "completed", "Draft", …) meant neither could.
STATUSES = {"draft", "in-progress", "complete", "abandoned", "superseded"}
REQUIRED_KEYS = ("id", "title", "status", "created", "tags")


def _frontmatter(path: pathlib.Path) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    if not match:
        return {}
    return dict(re.findall(r"^(\w+):\s*(.*?)\s*(?:#.*)?$", match.group(1), re.M))


def test_every_spec_status_is_from_the_vocabulary():
    bad = [(p.name, _frontmatter(p).get("status")) for p in SPEC_FILES if _frontmatter(p).get("status") not in STATUSES]
    assert not bad, f"status must be one of {sorted(STATUSES)}: {bad}"


def test_every_spec_has_the_required_frontmatter():
    missing = [(p.name, [k for k in REQUIRED_KEYS if k not in _frontmatter(p)]) for p in SPEC_FILES]
    missing = [m for m in missing if m[1]]
    assert not missing, f"specs missing frontmatter keys: {missing}"


def test_a_complete_spec_has_no_open_criteria():
    """`complete` meant "merged" for a while, so seven specs carried unticked criteria under it.
    An unmet criterion is either still open (`in-progress`) or said out loud (Dropped / Deferred /
    Superseded, without a checkbox)."""
    open_items = [
        p.name
        for p in SPEC_FILES
        if _frontmatter(p).get("status") == "complete" and re.search(r"^\s*- \[ \]", p.read_text(), re.M)
    ]
    assert not open_items, f"complete specs with unticked criteria: {open_items}"
