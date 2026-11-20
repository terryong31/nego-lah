"""Dependency hygiene guards (SPEC-115).

Archived upstream libraries (such as `langchain-community` and its legacy
companion `langchain-classic`) no longer receive security fixes and are flagged
by `uv audit`. The backend uses dedicated partner packages
(`langchain-google-genai`, `langchain-openai`), `langchain-core`, `langgraph`,
and `ddgs` directly, so archived wrappers must not creep back into
`pyproject.toml`, `uv.lock`, or Python imports.
"""

import ast
import re
import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = BACKEND_ROOT / "pyproject.toml"
UV_LOCK_PATH = BACKEND_ROOT / "uv.lock"

ARCHIVED_PACKAGES = frozenset({"langchain-community", "langchain-classic"})
ARCHIVED_MODULES = frozenset({"langchain_community", "langchain_classic"})
SKIP_DIRS = frozenset({".venv", "__pycache__", ".pytest_cache", "htmlcov"})

_DEP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _normalize_pkg_name(spec: str) -> str:
    match = _DEP_NAME_RE.match(spec.strip())
    assert match is not None, f"Could not parse package name from dependency spec: {spec!r}"
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _iter_backend_python_files():
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        if SKIP_DIRS.intersection(path.relative_to(BACKEND_ROOT).parts):
            continue
        yield path


def test_no_archived_packages_in_pyproject():
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    declared: list[str] = list(data.get("project", {}).get("dependencies", []))
    for group_deps in data.get("dependency-groups", {}).values():
        declared.extend(d for d in group_deps if isinstance(d, str))
    for opt_deps in data.get("project", {}).get("optional-dependencies", {}).values():
        declared.extend(d for d in opt_deps if isinstance(d, str))

    normalized = {_normalize_pkg_name(spec) for spec in declared}
    found = sorted(ARCHIVED_PACKAGES & normalized)
    assert not found, f"Archived packages declared in pyproject.toml: {found}"


def test_no_archived_packages_in_uv_lock():
    data = tomllib.loads(UV_LOCK_PATH.read_text(encoding="utf-8"))
    locked = {
        _normalize_pkg_name(pkg["name"])
        for pkg in data.get("package", [])
        if isinstance(pkg, dict) and "name" in pkg
    }
    found = sorted(ARCHIVED_PACKAGES & locked)
    assert not found, f"Archived packages present in uv.lock: {found}"


def test_no_archived_package_imports_in_backend():
    violations: list[str] = []
    for path in _iter_backend_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(BACKEND_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in ARCHIVED_MODULES:
                        violations.append(f"{rel}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in ARCHIVED_MODULES:
                    violations.append(f"{rel}:{node.lineno}: from {node.module} import ...")

    assert not violations, "Archived module imports found:\n" + "\n".join(violations)
