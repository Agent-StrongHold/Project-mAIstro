"""Gate: production code must not build a per-request `httpx.AsyncClient`.

Constructing a client builds a TLS context, a connection pool and a transport,
then throws all three away — 56.685ms of CPU per request against 1.241ms for a
pooled one, plus a fresh TCP+TLS handshake with no pool left to reuse.
`maistro.http.shared_client` exists so a call site gets pooling with a one-line
change.

## Why a gate rather than a one-time sweep

The migration that introduced `shared_client` was driven by a regex over
`async with httpx.AsyncClient(...) as client:`, and it missed every site
written in the parenthesized multi-line form:

    async with (
        httpx.AsyncClient(timeout=120.0) as client,
        client.stream("POST", url, json=payload) as r,
    ):

Three survived — both streaming paths in `adapters/llm_http.py` and the
chat-completions call in `services/graph_runner.py`. All three are LLM calls,
which is to say the hottest path in the application and precisely what the
change existed to fix. `llm_http.py` already imported `shared_client` for its
*other* sites, so the file looked migrated from every angle except this one.

Grepping does not catch it either: the module imports the helper, uses it, and
is covered by passing tests. This is the same shape as the reachability gate's
subject — a control that is present, plumbed and believed, with a path that
never reaches it — so it gets the same treatment: enumerate mechanically, and
make every exception state its reason.

Being unpooled is not automatically wrong. A client held for an object's
lifetime is already doing the right thing, and some transports can't be shared.
Those are listed below with why; anything else is a new per-request client.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories holding production code. Tests legitimately construct their own
# clients — a test that wants an isolated client should get one.
SOURCE_ROOTS = (
    "packages/maistro-core/src",
    "packages/maistro-server/src",
    "packages/maistro-canvas/src",
    "packages/maistro-turing/src",
    "packages/maistro-evolve/src",
    "packages/maistro-design/src",
    "packages/maistro-rsi/src",
    "packages/maistro-bootstrap/src",
    "packages/hive-conductor/backend",
)

# Every construction site that is deliberately not pooled, with the reason it
# is exempt. A bare path is not enough — adding an entry means writing down why
# this site is different, which is the part a reviewer can actually check.
ALLOWED: dict[str, str] = {
    "packages/maistro-core/src/maistro/http.py": (
        "the pool itself — this is the one place a client is constructed"
    ),
    "packages/maistro-evolve/src/maistro_evolve/providers/openai_compatible.py": (
        "maistro-evolve does not depend on maistro-core, and taking that dependency "
        "to pool one call site would couple a standalone optimizer to the whole core "
        "runtime; sets explicit httpx.Limits instead"
    ),
    "packages/hive-conductor/backend/routes/containers.py": (
        "unix-domain-socket transport to the Docker socket — no TLS handshake to "
        "amortize, and the transport cannot be shared with TCP call sites"
    ),
    "packages/maistro-design/src/maistro_design/providers/open_design.py": (
        "injectable client_factory used as a MockTransport seam; the caller closes "
        "what the factory returns, which would close a shared client"
    ),
}


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        files.extend(
            p
            for p in base.rglob("*.py")
            # hive-conductor keeps its tests under backend/tests
            if "tests" not in p.relative_to(base).parts
        )
    return files


def _is_async_client_call(node: ast.AST) -> bool:
    """True for `httpx.AsyncClient(...)` and a bare `AsyncClient(...)`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "AsyncClient"
    return isinstance(func, ast.Name) and func.id == "AsyncClient"


def _construction_sites(path: Path) -> list[int]:
    """Line numbers of AsyncClient constructions in real code.

    Parsing rather than grepping is load-bearing: two modules embed httpx
    snippets in the source strings they hand to a subprocess, and those run in
    a separate process where sharing means nothing. An earlier regex pass
    rewrote them by mistake. The AST does not see inside a string constant, so
    the distinction is free here.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    return sorted({n.lineno for n in ast.walk(tree) if _is_async_client_call(n)})


def test_no_unpooled_client_construction() -> None:
    offenders: list[str] = []
    for path in _iter_source_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED:
            continue
        for lineno in _construction_sites(path):
            offenders.append(f"{rel}:{lineno}")

    assert not offenders, (
        "These sites construct an httpx.AsyncClient per use instead of using "
        "`maistro.http.shared_client`:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse `async with shared_client(timeout=...) as client:` — it is a "
        "drop-in that pools and does not close on exit, so it composes with "
        "`client.stream(...)` unchanged. If the site genuinely must not be "
        "pooled, add it to ALLOWED with the reason."
    )


@pytest.mark.parametrize("rel", sorted(ALLOWED))
def test_every_allowlist_entry_still_constructs_a_client(rel: str) -> None:
    """An allowlist that outlives its entries stops describing the code.

    If a site is refactored to pool (or deleted), its exemption should go with
    it rather than sit there silently permitting a future regression in a file
    nobody looks at again.
    """
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} is allowlisted but does not exist"
    assert _construction_sites(path), (
        f"{rel} is allowlisted as constructing an httpx.AsyncClient, but no "
        "construction remains. Drop the ALLOWED entry."
    )


def test_the_scan_actually_finds_files() -> None:
    """Guard against the vacuous pass — if the walk returned nothing, every
    assertion above would hold while checking nothing at all."""
    files = _iter_source_files()
    assert len(files) > 500, f"only {len(files)} source files scanned; the walk is broken"
