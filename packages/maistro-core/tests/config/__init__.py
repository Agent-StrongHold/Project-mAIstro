"""Proxy Hive's flat config only when the monorepo imports it as ``config``.

Pytest's importlib mode gives this test package the same top-level name as
Hive Conductor's backend ``config.py``. Lazy loading keeps the maistro config
suite isolated while allowing backend modules to use their normal flat import
when both suites are collected together.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_BACKEND_CONFIG = (
    Path(__file__).resolve().parents[4] / "packages" / "hive-conductor" / "backend" / "config.py"
)


def _load_backend_config() -> Any:
    spec = importlib.util.spec_from_file_location("_hive_backend_config", _BACKEND_CONFIG)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load Hive backend config from {_BACKEND_CONFIG}")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for name, value in vars(module).items():
        if not name.startswith("__"):
            globals()[name] = value
    return module


def __getattr__(name: str) -> Any:
    """Load the app config only for a backend flat import."""
    module = _load_backend_config()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
