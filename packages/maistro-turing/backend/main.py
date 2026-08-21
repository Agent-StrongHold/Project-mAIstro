"""Turing backend FastAPI entrypoint.

A small, standalone service that imports the maistro_turing library and exposes
the live/admin/chat surface for the Turing self-model frontend. Distinct from
hive-conductor; runs on its own port (default 8120).

Two auth lanes (see middleware/auth.py): human session cookies for the dashboard
/ feed / chat / admin, and a narrowly-scoped Turing-internal service key for
Turing's own producers to publish artifacts.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import build_registry, cors_origins
from .middleware.auth import TuringAuthMiddleware
from .routes import admin, auth, chat, feed, health, state


def create_app() -> FastAPI:
    app = FastAPI(title="Turing Backend", version="0.9.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TuringAuthMiddleware, registry=build_registry())

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/v1/auth")
    app.include_router(state.router, prefix="/v1/state")
    app.include_router(feed.router, prefix="/v1/feed")
    app.include_router(chat.router, prefix="/v1/chat")
    app.include_router(admin.router, prefix="/v1/admin")

    return app


app = create_app()
