"""Optional PostgreSQL persistence via PostgREST. Graceful no-op if not configured."""

import os

from maistro.http import shared_client

POSTGREST_URL = (
    os.environ.get("DEPLOY_TARGET_POSTGREST_URL") or os.environ.get("POSTGREST_URL") or ""
)


async def pg_get(table: str, params: dict) -> list:
    if not POSTGREST_URL:
        return []
    async with shared_client(timeout=5) as c:
        r = await c.get(f"{POSTGREST_URL}/{table}", params=params)
        return r.json() if r.status_code == 200 else []


async def pg_upsert(table: str, data: dict) -> dict | None:
    if not POSTGREST_URL:
        return None
    async with shared_client(timeout=5) as c:
        r = await c.post(
            f"{POSTGREST_URL}/{table}",
            json=data,
            headers={
                "Prefer": "resolution=merge-duplicates,return=representation",
                "Content-Type": "application/json",
            },
        )
        rows = r.json() if r.status_code in (200, 201) else []
        return rows[0] if rows else None


async def pg_delete(table: str, params: dict) -> None:
    if not POSTGREST_URL:
        return
    async with shared_client(timeout=5) as c:
        await c.delete(f"{POSTGREST_URL}/{table}", params=params)


def is_pg_available() -> bool:
    return bool(POSTGREST_URL)
