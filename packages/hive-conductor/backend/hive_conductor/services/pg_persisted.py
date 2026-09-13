"""Synchronous PostgREST-backed store for route/service state.

Complements ``pg_store`` (async helpers): this is the sync interface used by
code paths that load/save whole tables outside an event loop — startup
seeding, layout mirrors, CLI tooling. Graceful no-op when PostgREST isn't
configured: reads return empty, writes return None.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("hive.pg_persisted")


def _postgrest_url() -> str:
    return os.environ.get("DEPLOY_TARGET_POSTGREST_URL") or os.environ.get("POSTGREST_URL") or ""


class PgPersistedStore:
    """Thin sync wrapper over PostgREST for whole-table state persistence.

    Every method is fail-safe: connection/HTTP errors degrade to the
    "not configured" behaviour rather than raising, so callers can layer
    this over in-memory state without guarding each call.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(_postgrest_url())

    def list_all_raw(self, table: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Return all rows of ``table`` (optionally filtered); [] if unavailable."""
        base = _postgrest_url()
        if not base:
            return []
        try:
            r = httpx.get(f"{base}/{table}", params=params or {}, timeout=self._timeout)
            return r.json() if r.status_code == 200 else []
        except Exception as e:
            logger.debug("pg list_all_raw(%s) failed: %s", table, e)
            return []

    def get_raw(self, table: str, params: dict[str, Any]) -> dict | None:
        """Return the first row matching ``params``; None if unavailable/missing."""
        rows = self.list_all_raw(table, params)
        return rows[0] if rows else None

    def upsert_raw(self, table: str, data: dict[str, Any]) -> dict | None:
        """Insert-or-merge ``data``; returns the stored row or None."""
        base = _postgrest_url()
        if not base:
            return None
        try:
            r = httpx.post(
                f"{base}/{table}",
                json=data,
                headers={
                    "Prefer": "resolution=merge-duplicates,return=representation",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
            rows = r.json() if r.status_code in (200, 201) else []
            return rows[0] if rows else None
        except Exception as e:
            logger.debug("pg upsert_raw(%s) failed: %s", table, e)
            return None

    def delete_raw(self, table: str, params: dict[str, Any]) -> bool:
        """Delete rows matching ``params``; False if unavailable/failed."""
        base = _postgrest_url()
        if not base:
            return False
        try:
            r = httpx.delete(f"{base}/{table}", params=params, timeout=self._timeout)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.debug("pg delete_raw(%s) failed: %s", table, e)
            return False
