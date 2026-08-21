"""Locate maistro-engine monorepo root (directory containing root `docker-compose.yml`)."""

from __future__ import annotations

import os
from pathlib import Path


def find_maistro_engine_root(start: Path | None = None) -> Path | None:
    """Walk parents for `docker-compose.yml` that defines the `maistro-engine` service."""
    env = os.environ.get("MAISTRO_REPO_ROOT", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if _is_engine_root(p):
            return p
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if _is_engine_root(d):
            return d
    return None


def _is_engine_root(d: Path) -> bool:
    compose = d / "docker-compose.yml"
    if not compose.is_file():
        return False
    try:
        text = compose.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "maistro-engine:" not in text:
        return False
    pp = d / "pyproject.toml"
    if not pp.is_file():
        return True
    try:
        ptxt = pp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return 'name = "maistro-workspace"' in ptxt
