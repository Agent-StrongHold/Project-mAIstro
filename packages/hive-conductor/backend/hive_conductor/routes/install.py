from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

router = APIRouter(tags=["install"])


def _bootstrap_or_503():
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
    from maistro_bootstrap.schema import describe_validation_error  # present if fn resolved

    try:
        return fn(partial=body)
    except ValidationError as exc:
        # #810: unknown answer keys are a 422 that names the key — never a
        # silent default or an opaque 500.
        raise HTTPException(status_code=422, detail=describe_validation_error(exc)) from exc
