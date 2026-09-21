"""Lazy attribute resolution for domain packages.

`domains/<d>/__init__.py` is the domain's public face, but the logic now lives
inside the same package. Importing a router eagerly from `__init__` would
re-enter the package mid-import, so every export resolves on first access
instead.
"""

from importlib import import_module


def lazy_getattr(package: str, table: dict[str, tuple[str, str]]):
    """Build a module-level `__getattr__` from {export: (module, attribute)}."""

    def __getattr__(name: str):
        target = table.get(name)
        if target is None:
            raise AttributeError(f"module {package!r} has no attribute {name!r}")
        module_name, attr = target
        return getattr(import_module(module_name), attr)

    return __getattr__
