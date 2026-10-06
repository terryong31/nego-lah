"""
Architectural boundary tests (ADR-0002, SPEC-002, SPEC-092, SPEC-095, AGENTS.md Rule 3).

AGENTS.md §3 states two rules: a domain must never query another domain's tables,
and cross-domain work goes through the other domain's *package*, never a module
inside it. This file enforces both.

A file's owning domain is READ OFF ITS PATH rather than looked up in a
hand-maintained map. That is the point of SPEC-092's move: the boundary is a
directory, so it cannot silently drift from whatever a map happens to say.

SPEC-095 closed three holes in the first version of this file:

* the import rule walked only `domains/`, so every non-domain file — `main.py`,
  `admin_api.py`, `services/` — was unchecked, and all of them were violating it;
* the table scan matched `.table("literal")` only, so a table name held in a
  variable was invisible to it;
* `NON_DOMAIN_FILES` exempted four files that query no tables at all, which only
  weakened `test_all_persistence_lives_inside_a_domain`.

`KNOWN_VIOLATIONS` is a ratchet, not an exemption list. A violation that is not
listed fails the build; a listed violation that has been fixed ALSO fails the
build, so the list can only shrink. Fix one, delete its line.
"""

import ast
import re
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DOMAINS = BACKEND / "domains"

DOMAIN_NAMES = {"catalog", "negotiation", "billing", "identity", "webhooks"}

# The layering (SPEC-097). A domain may import STRICTLY BELOW itself and nothing
# else. An order needs an item, so billing sits above catalog; the agent needs
# both, so negotiation sits on top and nothing may depend on it. `webhooks` is
# an inbound edge that depends on nobody, so its rank only has to be defined.
#
# Before SPEC-097 these four formed a fully connected cyclic graph — 24 cycles
# over 8 back-edges — which is the difference between a modular monolith and a
# ball of mud wearing directory names.
DOMAIN_RANK: dict[str, int] = {
    "identity": 0,
    "catalog": 1,
    "billing": 2,
    "negotiation": 3,
    "webhooks": 4,
}

# The one place allowed to depend on every domain: application composition, not
# a bounded context. A domain importing it would invert the whole arrangement.
COMPOSITION_ROOT = "console"

REPO_ROOT = BACKEND.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

# Not source we own, or not Python we wrote.
_INFRA = {".venv", "htmlcov", "__pycache__", "migrations"}

# Developer tooling, exempt from both rules BY DESIGN. An eval harness scores the
# agent's internals and ops scripts exist to reach past the application — holding
# them to the public contract would mean widening that contract for no caller.
# Production code gets no such exemption.
_TOOLING = {"tests", "scripts", "evals", "conftest.py"}

# Which domain owns which table. A table belongs to exactly one bounded context.
TABLE_OWNER: dict[str, str] = {
    "items": "catalog",
    "orders": "billing",
    "transactions": "billing",
    "messages": "negotiation",
    "chat_settings": "negotiation",
    "user_profiles": "identity",
    "admin_audit_log": "identity",
    # Pre-SPEC-043 chat history (one row per user, messages in a jsonb array).
    # Superseded by `messages`, backfilled from, and never dropped — so it is
    # still negotiation's, and saying so is what keeps a stray query to it from
    # looking like it belongs to whoever writes that query.
    "conversations": "negotiation",
}

# The ratchet. Empty is the goal.
KNOWN_VIOLATIONS: set[tuple[str, str]] = set()


def _production_files() -> list[tuple[str, Path]]:
    """Every backend file both rules apply to, as (relative posix path, path)."""
    files = []
    for path in BACKEND.rglob("*.py"):
        parts = path.relative_to(BACKEND).parts
        if any(part in _INFRA or part in _TOOLING for part in parts):
            continue
        files.append((path.relative_to(BACKEND).as_posix(), path))
    return sorted(files)


def _owner_of(rel_path: str) -> str | None:
    """A file's domain is the directory it lives in: domains/<name>/…"""
    parts = Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "domains":
        return parts[1]
    return None


def _table_calls() -> list[tuple[str, ast.Call]]:
    """Every `<x>.table(...)` call in production code, literal or not."""
    calls = []
    for rel, path in _production_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table":
                calls.append((rel, node))
    return calls


def _table_accesses() -> dict[tuple[str, str], list[int]]:
    """Every literal `.table("name")` call in backend production code."""
    found: dict[tuple[str, str], list[int]] = defaultdict(list)
    for rel, node in _table_calls():
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            found[(rel, node.args[0].value)].append(node.lineno)
    return found


def _cross_domain_imports(include_package_imports: bool = False) -> list[tuple[str, str, int]]:
    """
    Every import of another domain's *private module*, as (file, module, line).

    For a file inside a domain, its own package is its own business. For a file
    outside every domain, all five domains are foreign.
    """
    offenders = []
    for rel, path in _production_files():
        current = _owner_of(rel)
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # `from . import x` inside a domain stays inside it.
                if node.level or not node.module:
                    continue
                module = node.module
            elif isinstance(node, ast.Import):
                module = next((a.name for a in node.names if a.name.startswith("domains.")), None)
                if module is None:
                    continue
            else:
                continue

            parts = module.split(".")
            if parts[0] != "domains" or len(parts) < 2 or parts[1] == current:
                continue
            # The private-module rule needs `domains.x.y`; the dependency graph
            # needs `domains.x` too, since a package import is still an edge.
            if len(parts) > 2 or include_package_imports:
                offenders.append((rel, module, node.lineno))
    return offenders


# --------------------------------------------------------------------------
# The scanners themselves
# --------------------------------------------------------------------------


def test_scanner_actually_finds_table_accesses():
    """
    Guard the guard: a scanner that silently matches nothing proves nothing.

    The floor is deliberately loose. Consolidating reads behind domain services
    drives this number DOWN — that is the migration working, not the scanner
    breaking — so this only has to catch a scanner that has stopped matching.
    """
    accesses = _table_accesses()
    assert len(accesses) > 10, f"scanner found only {len(accesses)} table accesses — it is not working"
    assert any(table == "items" for _, table in accesses)
    assert any(table == "orders" for _, table in accesses)


def test_scanner_covers_the_non_domain_production_files():
    """
    SPEC-095: the import rule used to walk only `domains/`, where no file could
    violate it in the ways the non-domain files were violating it. If this set
    ever empties, the backend-wide rules below are green by construction again.
    """
    scanned = {rel for rel, _ in _production_files()}
    for expected in ("main.py", f"{COMPOSITION_ROOT}/admin_api.py", f"{COMPOSITION_ROOT}/admin_dashboard.py"):
        assert expected in scanned, f"{expected} is not being scanned"
    assert any(rel.startswith("core/") for rel in scanned)
    assert any(rel.startswith(f"{COMPOSITION_ROOT}/") for rel in scanned)


def test_tooling_is_excluded_by_design():
    """The exemption is deliberate and narrow — assert its shape, not its spirit."""
    scanned = {rel for rel, _ in _production_files()}
    assert not any(rel.startswith(("tests/", "scripts/", "evals/")) for rel in scanned)
    assert "conftest.py" not in scanned


# --------------------------------------------------------------------------
# Table ownership
# --------------------------------------------------------------------------


def test_every_table_is_owned_by_a_domain():
    unknown = {table for _, table in _table_accesses() if table not in TABLE_OWNER}
    assert not unknown, f"tables with no owner in TABLE_OWNER: {sorted(unknown)} — add them."


def test_every_table_name_is_a_literal():
    """
    SPEC-095: ownership is decided by reading the table name at rest, so a name
    that only exists at runtime is a hole in the rule, not a style preference.
    Spell the table out, even when it costs a line.
    """
    dynamic = [
        f"  {rel}:{node.lineno}"
        for rel, node in _table_calls()
        if not (node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str))
    ]
    assert not dynamic, "Non-literal table names are invisible to the boundary scanner:\n" + "\n".join(dynamic)


def test_all_persistence_lives_inside_a_domain():
    """
    The whole point of the migration: if a file queries a table, it is domain
    code and belongs under `domains/<name>/`. Anything else is a module that
    escaped the move.
    """
    stray = sorted({path for path, _ in _table_accesses() if _owner_of(path) is None})
    assert not stray, f"These files query tables but do not live in a domain — move them under domains/<name>/: {stray}"


def test_no_cross_domain_table_access():
    """AGENTS.md §3: a domain must never query another domain's private tables."""
    violations: set[tuple[str, str]] = set()
    detail: dict[tuple[str, str], list[int]] = {}

    for (path, table), lines in _table_accesses().items():
        owner = _owner_of(path)
        if owner is None:
            continue
        if owner != TABLE_OWNER[table]:
            violations.add((path, table))
            detail[(path, table)] = lines

    new = violations - KNOWN_VIOLATIONS
    assert not new, "Cross-domain table access (route it through the owning domain's service):\n" + "\n".join(
        f"  {p}:{detail[(p, t)]} queries '{t}' ({_owner_of(p)} -> {TABLE_OWNER[t]})" for p, t in sorted(new)
    )


def test_known_violations_list_has_not_gone_stale():
    """The ratchet only turns one way: a fixed violation must leave the list."""
    violations = {
        (path, table)
        for (path, table) in _table_accesses()
        if (owner := _owner_of(path)) is not None and owner != TABLE_OWNER[table]
    }
    fixed = KNOWN_VIOLATIONS - violations
    assert not fixed, f"These are fixed — delete them from KNOWN_VIOLATIONS so the ratchet holds: {sorted(fixed)}"


# --------------------------------------------------------------------------
# Package contracts
# --------------------------------------------------------------------------


def test_no_production_file_imports_a_domains_private_module():
    """
    A domain's `__init__.py` is its contract. Everything else inside it is
    private — to other domains AND to `main.py`, `admin_api.py` and `services/`,
    which is where SPEC-092's version of this rule stopped looking.

    `from domains.identity import IdentityService` is fine.
    `from domains.identity.profiles import …` is not. If a caller outside the
    domain needs it, the domain should export it.
    """
    offenders = _cross_domain_imports()
    assert not offenders, "Private cross-domain imports — use the domain's exported contract:\n" + "\n".join(
        f"  {rel}:{line} imports '{module}'" for rel, module, line in sorted(offenders)
    )


def test_core_never_imports_a_domain():
    """
    Shared infrastructure is the bottom of the stack. If `core/` reaches up into
    a domain, the dependency is inverted and the domains stop being removable.
    """
    offenders = []
    for rel, path in _production_files():
        if not rel.startswith("core/"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("domains"):
                offenders.append(f"  {rel}:{node.lineno} imports '{node.module}'")
            elif isinstance(node, ast.Import):
                offenders += [f"  {rel}:{node.lineno} imports '{a.name}'" for a in node.names if a.name.startswith("domains")]
    assert not offenders, "core/ must not depend on a domain — that inverts the stack:\n" + "\n".join(offenders)


def test_every_domain_exports_a_contract():
    """A bounded context with no public surface cannot be imported correctly."""
    for domain in sorted(DOMAIN_NAMES):
        init = DOMAINS / domain / "__init__.py"
        assert init.exists(), f"domains/{domain}/__init__.py is missing"
        source = init.read_text()
        assert "lazy_getattr" in source, (
            f"domains/{domain}/__init__.py must export through domains/_lazy.py — an eager import "
            "re-enters the package mid-import and drags LangChain into boot"
        )


# --------------------------------------------------------------------------
# The shape of the monolith (SPEC-097)
# --------------------------------------------------------------------------


def _domain_edges() -> list[tuple[str, str, str, int]]:
    """Every cross-domain dependency, as (from, to, file, line)."""
    edges = []
    for rel, module, line in _cross_domain_imports(include_package_imports=True):
        owner = _owner_of(rel)
        target = module.split(".")[1] if module.startswith("domains.") else None
        if owner and target and target in DOMAIN_NAMES and target != owner:
            edges.append((owner, target, rel, line))
    return edges


def test_every_domain_has_a_rank():
    """A domain with no declared position cannot be checked against the others."""
    assert set(DOMAIN_RANK) == DOMAIN_NAMES, (
        f"DOMAIN_RANK and DOMAIN_NAMES disagree: {set(DOMAIN_RANK) ^ DOMAIN_NAMES}"
    )
    assert len(set(DOMAIN_RANK.values())) == len(DOMAIN_RANK), "two domains share a rank — the order is not total"


def test_no_domain_depends_on_one_at_or_above_its_own_rank():
    """
    THE rule (SPEC-097). Everything else in this file checks how a dependency is
    written; this checks whether it is allowed to exist.

    A back-edge is not fixed by re-exporting the callee somewhere else — that
    just hides it. Either move the code to `console/`, or invert the direction
    through `core/bus.py` so the lower domain never names the higher one.
    """
    offenders = [
        f"  {rel}:{line}  {src} -> {dst}   (rank {DOMAIN_RANK[src]} -> {DOMAIN_RANK[dst]})"
        for src, dst, rel, line in sorted(_domain_edges())
        if DOMAIN_RANK[dst] >= DOMAIN_RANK[src]
    ]
    order = " < ".join(name for name, _ in sorted(DOMAIN_RANK.items(), key=lambda kv: kv[1]))
    assert not offenders, f"Dependencies that break the layering ({order}):\n" + "\n".join(offenders)


def test_the_domain_graph_has_no_cycles():
    """
    Stated independently of the rank, because a rank can be edited to make a
    cycle legal. This one cannot be argued with: it walks the real edges.
    """
    graph: dict[str, set[str]] = {d: set() for d in DOMAIN_NAMES}
    for src, dst, _, _ in _domain_edges():
        graph[src].add(dst)

    cycles: set[tuple[str, ...]] = set()

    def visit(node: str, path: list[str]) -> None:
        for nxt in sorted(graph[node]):
            if nxt in path:
                cycle = path[path.index(nxt) :] + [nxt]
                cycles.add(tuple(cycle))
            else:
                visit(nxt, path + [nxt])

    for start in sorted(DOMAIN_NAMES):
        visit(start, [start])

    assert not cycles, "Cyclic domain dependencies:\n" + "\n".join(
        "  " + " -> ".join(c) for c in sorted(cycles, key=len)
    )


def test_no_domain_imports_the_composition_root():
    """`console/` composes domains. A domain that imports it inverts the stack."""
    offenders = []
    for rel, path in _production_files():
        if _owner_of(rel) is None:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if name == COMPOSITION_ROOT or name.startswith(f"{COMPOSITION_ROOT}."):
                    offenders.append(f"  {rel}:{node.lineno} imports '{name}'")
    assert not offenders, f"Domains must not import {COMPOSITION_ROOT}/:\n" + "\n".join(offenders)


def test_core_never_imports_a_domain_or_the_composition_root():
    """
    Shared infrastructure is the bottom of the stack. If `core/` reaches up, the
    dependency is inverted and the domains stop being removable.
    """
    offenders = []
    for rel, path in _production_files():
        if not rel.startswith("core/"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if name.split(".")[0] in {"domains", COMPOSITION_ROOT}:
                    offenders.append(f"  {rel}:{node.lineno} imports '{name}'")
    assert not offenders, "core/ must not depend on a domain or on console/:\n" + "\n".join(offenders)


def test_there_is_no_fourth_layer():
    """
    `services/` was neither a domain nor infrastructure, and four domains
    imported it. Everything now belongs to exactly one of three layers, so a new
    top-level package is a decision, not a drift.
    """
    allowed = {"core", "domains", COMPOSITION_ROOT, "tests", "scripts", "evals", "templates"}
    strays = sorted(
        d.name
        for d in BACKEND.iterdir()
        if d.is_dir() and (d / "__init__.py").exists() and d.name not in allowed and not d.name.startswith(".")
    )
    assert not strays, f"Top-level packages that are not a recognised layer: {strays}"


# --------------------------------------------------------------------------
# Table ownership is driven by the schema, not by what code happens to query
# --------------------------------------------------------------------------


def _tables_in_schema() -> set[str]:
    """Every table the migrations create. SQL comments stripped first —
    `baseline_schema.sql` contains the prose 'Uses CREATE TABLE IF NOT EXISTS so
    it is safe…', which a naive scan reads as a table called `so`."""
    tables: set[str] = set()
    for sql_file in MIGRATIONS_DIR.glob("*.sql"):
        body = re.sub(r"--[^\n]*", "", sql_file.read_text())
        for match in re.finditer(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?([a-z_][a-z0-9_]*)", body, re.I):
            tables.add(match.group(1).lower())
    return tables


def test_the_schema_parser_finds_the_known_tables():
    """Guard the guard: a regex that matches nothing would make the next test vacuous."""
    tables = _tables_in_schema()
    assert {"items", "orders", "messages", "user_profiles"} <= tables, f"parser found: {sorted(tables)}"
    assert "so" not in tables, "SQL comments are not being stripped"


def test_every_table_in_the_schema_has_an_owning_domain():
    """
    `test_every_table_is_owned_by_a_domain` only sees tables some file queries,
    so a table nobody touches has no owner and nothing notices — which is how it
    gets adopted by whichever domain queries it first (SPEC-097).
    """
    unowned = sorted(_tables_in_schema() - set(TABLE_OWNER))
    assert not unowned, f"Tables created by a migration with no entry in TABLE_OWNER: {unowned}"


def test_table_owner_has_no_entries_for_tables_that_do_not_exist():
    """The map shrinks when a table is dropped, or it becomes folklore."""
    ghosts = sorted(set(TABLE_OWNER) - _tables_in_schema())
    assert not ghosts, f"TABLE_OWNER names tables no migration creates: {ghosts}"
