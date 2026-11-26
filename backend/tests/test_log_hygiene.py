"""Log hygiene checks for backend production code (SPEC-117)."""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
_SKIP_PARTS = {".venv", "htmlcov", "__pycache__", "migrations", "tests", "scripts", "evals", "conftest.py"}
_LOGGER_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception"}
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_BANNER_RE = re.compile(r"={5,}")
_LOG_COMMENT_RE = re.compile(r"^\s*#\s*LOG:", re.MULTILINE)


def _production_files() -> list[tuple[str, Path]]:
    files = []
    for path in BACKEND.rglob("*.py"):
        parts = path.relative_to(BACKEND).parts
        if any(part in _SKIP_PARTS for part in parts):
            continue
        files.append((path.relative_to(BACKEND).as_posix(), path))
    return sorted(files)


def _iter_logger_string_constants(tree: ast.AST):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOGGER_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        yield node.lineno, sub.value
                    # Catch f"{'=' * 50}" style divider banners
                    if (
                        isinstance(sub, ast.BinOp)
                        and isinstance(sub.op, ast.Mult)
                        and isinstance(sub.left, ast.Constant)
                        and sub.left.value == "="
                    ):
                        yield node.lineno, "====="


def test_no_emojis_in_production_logger_calls():
    offenders: list[str] = []
    for rel, path in _production_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for lineno, text in _iter_logger_string_constants(tree):
            if _EMOJI_RE.search(text):
                offenders.append(f"{rel}:{lineno}: {text!r}")
    assert not offenders, "Emoji characters found in production logger calls:\n" + "\n".join(offenders)


def test_no_ascii_banner_logs_in_production():
    offenders: list[str] = []
    for rel, path in _production_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for lineno, text in _iter_logger_string_constants(tree):
            if _BANNER_RE.search(text) or text.startswith("\n"):
                offenders.append(f"{rel}:{lineno}: {text!r}")
    assert not offenders, "ASCII banner / leading-newline logs found in production:\n" + "\n".join(offenders)


def test_no_log_marker_comments_in_production():
    offenders: list[str] = []
    for rel, path in _production_files():
        source = path.read_text()
        for match in _LOG_COMMENT_RE.finditer(source):
            lineno = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{rel}:{lineno}")
    assert not offenders, "Prototype '# LOG:' comments found in production:\n" + "\n".join(offenders)
