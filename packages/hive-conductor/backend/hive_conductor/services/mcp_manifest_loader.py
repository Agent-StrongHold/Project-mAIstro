"""Load MCP server manifests from an external MCP_servers directory when
present, falling back to a directory bundled in this repo.

Tolerates two run environments:
  - Host (dev): if this package happens to be nested several levels inside
    a parent checkout that provides a sibling `container_registry/MCP_servers`
    directory, walk up to find it (see _PARENT_MCP_DIR below). That layout
    is specific to certain nested deployments and doesn't exist in a
    standalone checkout of this repo — the walk simply comes up empty there.
  - Container (prod): file lives at /app/backend/services/mcp_manifest_loader.py
    so parents[4] doesn't exist (and there's no MCP_servers on disk inside
    the image anyway — the canonical path is to mount the dir via whatever
    deployment config applies).

Both paths fall through to FALLBACK + MAISTRO_MCP_OVERRIDE_DIR env so the loader
never crashes startup.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("hive.mcp_manifest")


def _safe_parent(path: Path, depth: int) -> Path | None:
    """Walk `depth` parent levels; return None if we run out of parents
    (e.g. when running inside a container where the package lives close
    to root)."""
    try:
        return path.parents[depth]
    except IndexError:
        return None


_THIS_FILE = Path(__file__).resolve()
_MAISTRO_ROOT = _safe_parent(_THIS_FILE, 4)
# The optional parent checkout root is two more levels up, for the nested-
# deployment layout described in the module docstring above.
_PARENT_ROOT = _safe_parent(_MAISTRO_ROOT, 2) if _MAISTRO_ROOT else None
_PARENT_MCP_DIR = (_PARENT_ROOT / "container_registry" / "MCP_servers") if _PARENT_ROOT else None
_FALLBACK_MCP_DIR = (_MAISTRO_ROOT / "config" / "mcp_servers") if _MAISTRO_ROOT else None

# Override via env — point this at a mounted volume of
# container_registry/MCP_servers/ in whatever deployment config applies.
_OVERRIDE_DIR_ENV = "MAISTRO_MCP_OVERRIDE_DIR"


def mcp_manifest_dirs() -> list[Path]:
    dirs: list[Path] = []
    override = os.environ.get(_OVERRIDE_DIR_ENV)
    if override:
        p = Path(override).expanduser()
        if p.is_dir():
            dirs.append(p)
    if _PARENT_MCP_DIR and _PARENT_MCP_DIR.is_dir():
        dirs.append(_PARENT_MCP_DIR)
    if _FALLBACK_MCP_DIR and _FALLBACK_MCP_DIR.is_dir():
        dirs.append(_FALLBACK_MCP_DIR)
    return dirs


def load_manifest_files() -> list[dict[str, Any]]:
    """Parse *.json manifests (skip README)."""
    out: list[dict[str, Any]] = []
    for base in mcp_manifest_dirs():
        for path in sorted(base.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id"):
                    data["_manifest_path"] = str(path)
                    out.append(data)
            except Exception as exc:
                logger.warning("mcp_manifest_skip path=%s err=%s", path, exc)
    return out
