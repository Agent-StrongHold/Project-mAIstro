from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["install"])


def _ensure_bootstrap_on_path() -> None:
    repo = Path(__file__).resolve().parent.parent.parent.parent
    bp = repo / "packages" / "maistro-bootstrap" / "src"
    if bp.is_dir() and str(bp) not in sys.path:
        sys.path.insert(0, str(bp))


def _bootstrap_or_503():
    _ensure_bootstrap_on_path()
    try:
        from maistro_bootstrap.session import get_session_defaults

        return get_session_defaults
    except ImportError:
        raise HTTPException(status_code=503, detail="maistro-bootstrap not available") from None


@router.get("/session")
def get_install_session() -> dict[str, Any]:
    fn = _bootstrap_or_503()
    return fn()


@router.post("/session")
def post_install_session(body: dict[str, Any]) -> dict[str, Any]:
    fn = _bootstrap_or_503()
    return fn(partial=body)
