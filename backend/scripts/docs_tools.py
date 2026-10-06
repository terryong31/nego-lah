"""
Generated documentation (SPEC-102).

Two artefacts in `docs/` are derived from something else and rot the moment a
person maintains them by hand:

- `docs/api/openapi.json` is the app's own `app.openapi()`. It was hand-carried
  and missed every route added after SPEC-079.
- The spec and ADR index tables are the files' own frontmatter. The spec index
  listed 12 of 101 specs.

    uv run python -m scripts.docs_tools openapi   # mise run docs:openapi
    uv run python -m scripts.docs_tools index     # mise run docs:index
    uv run python -m scripts.docs_tools stale     # mise run docs:stale

`tests/test_docs.py` fails when either is stale, so the commands are the fix it
asks for, not a chore to remember.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = REPO_ROOT / "docs"
SPECS_DIR = DOCS_DIR / "specs"
ADR_DIR = DOCS_DIR / "adr"
OPENAPI_PATH = DOCS_DIR / "api" / "openapi.json"

BEGIN = "<!-- BEGIN GENERATED: do not edit by hand; run `mise run docs:index` -->"
END = "<!-- END GENERATED -->"


# --- OpenAPI -----------------------------------------------------------------


def openapi_document() -> dict:
    """The contract the running app actually serves (locally at /openapi.json)."""
    from main import app

    return app.openapi()


def write_openapi() -> None:
    OPENAPI_PATH.write_text(json.dumps(openapi_document(), indent=2, ensure_ascii=False) + "\n")


# --- Indexes -----------------------------------------------------------------


def _frontmatter(path: Path) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    if not match:
        return {}
    fields = re.findall(r"^(\w+):\s*(.*?)\s*(?:#.*)?$", match.group(1), re.M)
    return {k: v.strip("\"'") for k, v in fields}


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_spec_index() -> str:
    rows = ["| Spec | Title | Status |", "|------|-------|--------|"]
    for path in sorted(SPECS_DIR.glob("SPEC-*.md")):
        meta = _frontmatter(path)
        rows.append(
            f"| [{meta.get('id', path.stem)}]({path.name}) | {_cell(meta.get('title', ''))} | {meta.get('status', '')} |"
        )
    return "\n".join(rows) + "\n"


def adr_metadata(path: Path) -> dict[str, str]:
    """Title, status and date from an ADR's opening block.

    Every ADR starts the same way (see `docs/adr/TEMPLATE.md`):

        # ADR-0030: The domain graph is acyclic

        - Status: Accepted
        - Date: 2026-09-20
    """
    head = path.read_text().split("\n## ", 1)[0]
    title = re.search(r"^# ADR-\d{4}: (.+)$", head, re.M)
    status = re.search(r"^- Status: (.+)$", head, re.M)
    date = re.search(r"^- Date: (.+)$", head, re.M)
    if not (title and status and date):
        raise ValueError(f"{path.name}: needs '# ADR-NNNN: Title', '- Status:' and '- Date:' before the first section")
    return {"title": title.group(1).strip(), "status": status.group(1).strip(), "date": date.group(1).strip()}


def render_adr_index() -> str:
    rows = ["| ADR | Title | Status | Date |", "|-----|-------|--------|------|"]
    for path in sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        meta = adr_metadata(path)
        rows.append(f"| [{path.name[:4]}]({path.name}) | {_cell(meta['title'])} | {meta['status']} | {meta['date']} |")
    return "\n".join(rows) + "\n"


def generated_region(text: str) -> str:
    start, end = text.index(BEGIN) + len(BEGIN) + 1, text.index(END)
    return text[start:end]


def replace_generated_region(text: str, body: str) -> str:
    start, end = text.index(BEGIN) + len(BEGIN) + 1, text.index(END)
    return text[:start] + body + text[end:]


def write_indexes() -> None:
    for readme, body in ((SPECS_DIR / "README.md", render_spec_index()), (ADR_DIR / "README.md", render_adr_index())):
        readme.write_text(replace_generated_region(readme.read_text(), body))


# --- Staleness ---------------------------------------------------------------

# Each living doc, and the code whose change should make someone re-read it.
LIVING_DOCS: dict[str, list[str]] = {
    "docs/architecture/README.md": ["backend/main.py", "backend/core/bus.py", "docker-compose.yml"],
    "docs/architecture/agent.md": [
        "backend/domains/negotiation/bot.py",
        "backend/domains/negotiation/llm_factory.py",
        "backend/domains/negotiation/decide.py",
        "backend/domains/negotiation/speak.py",
        "backend/domains/negotiation/tools/*.py",
    ],
    "docs/data/README.md": ["supabase/migrations/*.sql"],
    "docs/api/README.md": ["backend/domains/identity/auth_routes.py", "backend/core/csrf.py"],
    "docs/workers/README.md": ["backend/main.py", "backend/domains/negotiation/unread_digest.py"],
    "docs/flows/README.md": ["backend/domains/billing/fulfillment.py", "backend/domains/negotiation/bot.py"],
    "docs/ci-cd/README.md": [".github/workflows/*.yml"],
    "docs/repo/README.md": ["mise.toml", "lefthook.yml"],
}


def _last_change(path: str) -> int:
    """Unix time of the last commit touching `path`; now, if it has uncommitted edits."""
    git = ["git", "-C", str(REPO_ROOT)]
    if subprocess.run([*git, "diff", "--quiet", "HEAD", "--", path], check=False).returncode:  # noqa: S603
        return int(time.time())
    out = subprocess.run([*git, "log", "-1", "--format=%ct", "--", path], capture_output=True, text=True, check=False)  # noqa: S603
    return int(out.stdout.strip() or 0)


def stale_docs(times: dict[str, int], files_by_doc: dict[str, list[str]]) -> list[tuple[str, str]]:
    """(doc, newest newer file) for every doc whose code changed after it did."""
    stale = []
    for doc, files in files_by_doc.items():
        newer = [f for f in files if times[f] > times[doc]]
        if newer:
            stale.append((doc, max(newer, key=times.__getitem__)))
    return stale


def report_stale() -> None:
    files_by_doc = {
        doc: sorted(str(p.relative_to(REPO_ROOT)) for g in globs for p in REPO_ROOT.glob(g))
        for doc, globs in LIVING_DOCS.items()
    }
    paths = set(files_by_doc) | {f for files in files_by_doc.values() for f in files}
    times = {p: _last_change(p) for p in paths}
    stale = stale_docs(times, files_by_doc)
    for doc, code in stale:
        prefix = f"::warning file={doc}::" if os.environ.get("GITHUB_ACTIONS") else "⚠️  "
        print(f"{prefix}{doc} is older than {code}; re-read it against the code.")
    if not stale:
        print("✅ Every living doc is newer than the code it describes.")


if __name__ == "__main__":
    commands = {"openapi": write_openapi, "index": write_indexes, "stale": report_stale}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: python -m scripts.docs_tools {{{'|'.join(commands)}}}")
    commands[sys.argv[1]]()
