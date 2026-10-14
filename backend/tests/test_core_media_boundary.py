"""SPEC-108 — `core/media.py` is the only production code that touches object storage.

Before SPEC-108 five call sites each did `admin_supabase.storage.from_(…)` and
stored whatever `get_public_url()` returned, which is how a vendor URL ended up
in every row and in front of the browser. The scan runs over the same
production files the domain-boundary scan does; scripts and tests are tooling.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
_SKIP = {".venv", "htmlcov", "__pycache__", "migrations", "tests", "scripts", "evals"}
_STORAGE_ATTRS = {"storage", "get_public_url"}
_ALLOWED = {"core/media.py"}


def _storage_accesses() -> list[tuple[str, int, str]]:
    found = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if any(part in _SKIP for part in rel.parts) or rel.name == "conftest.py":
            continue
        if rel.as_posix() in _ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Attribute) and node.attr in _STORAGE_ATTRS:
                found.append((rel.as_posix(), node.lineno, node.attr))
    return sorted(found)


def test_only_core_media_touches_object_storage():
    assert _storage_accesses() == []


def test_the_scan_would_see_a_storage_call(tmp_path):
    """Guard the guard: the attribute match is what a real call looks like."""
    tree = ast.parse("admin_supabase.storage.from_('images').get_public_url('x')")
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert _STORAGE_ATTRS <= attrs
