"""The Design Studio loop start mints canonical objects only (#988, M7-A12).

Opening work in Design Studio must mint a Goal revision, a CreativeBrief
revision, a pack binding, and one canonical Run (ADR-092926-7a01) — never a
product-local kind. This is the contract test for the #988 invariants: it
fails if a `DesignRun` kind/store/route, a client-persist system of record for
loop objects, or a pack-specific route (`/book`, `/game`, `/atelier`) is
introduced into the frontend.

The scan is static source, because the failure it guards (a second identity
kind or a localStorage system of record) is a code shape, not a runtime
response. Comments are stripped before the forbidden-identifier scan: prose
may (and should) say "there is no DesignRun"; code may not say it quietly.
"""

from __future__ import annotations

import re
from pathlib import Path

_PACKAGES = Path(__file__).resolve().parents[3]
_FRONTEND_SRC = _PACKAGES / "hive-conductor/frontend/src"

#: Any real occurrence of the forbidden product-local kind. Comments are
#: stripped first, so documentation of the prohibition never trips it.
DESIGN_RUN_RE = re.compile(r"\bDesignRun\b")

#: Client storage keys that name loop objects. The six shipped keys
#: (appearance, onboarding, ui mode/owner, active workspace, and the Design
#: Studio fixed-page artifact cache) name none of these words; a key that does
#: is a client-persist system of record for loop state (#988).
STORAGE_KEY_RE = re.compile(
    r"""(?:localStorage|sessionStorage)\.(?:set|get|remove)Item\(\s*["'`]([^"'`]+)["'`]""",
)
#: Substring match on purpose: `_` is a word character, so a `\b`-anchored
#: pattern would silently spare exactly the snake_case keys a loop store would
#: introduce (`hive_design_loop`). The six shipped keys contain none of these
#: substrings.
FORBIDDEN_KEY_WORD_RE = re.compile(r"designrun|goal|brief|pack|loop|run", re.IGNORECASE)

#: Route segments that would make a pack (or a Studio variant) a product
#: identity. Pack ids are bindings on the Run, never routes (#793/#988).
#: Both route shapes are read: JSX `<Route path="/book" ...>` and an
#: object-literal table `[{ path: "/book" }]` — a route table that moves off
#: JSX must not take the tripwire with it.
ROUTE_PATH_RE = re.compile(r"""path\s*[=:]\s*["'`]([^"'`]*)["'`]""")
FORBIDDEN_ROUTE_SEGMENT_RE = re.compile(
    r"(?:^|/)(?:book|game|product|atelier)(?:/|$)", re.IGNORECASE
)


def _strip_ts_comments(text: str) -> str:
    """Remove TS/TSX comments so documented prohibitions never self-trip.

    Conservative on purpose: block comments go first (DOTALL, non-greedy);
    line-comment tails are removed only for a `//` not preceded by `:`, so
    `https://` URLs survive. What remains is plenty for a tripwire whose job
    is catching a *declaration* of a forbidden kind.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"(?<!:)//[^\n]*", "", text)


def _frontend_sources() -> list[Path]:
    return sorted(
        path
        for pattern in ("*.ts", "*.tsx")
        for path in _FRONTEND_SRC.rglob(pattern)
        if "node_modules" not in path.parts
    )


def test_no_design_run_kind_store_or_route_exists_in_the_frontend() -> None:
    offenders: list[str] = []
    for path in _frontend_sources():
        if DESIGN_RUN_RE.search(_strip_ts_comments(path.read_text(encoding="utf-8"))):
            offenders.append(str(path.relative_to(_PACKAGES)))
    assert not offenders, (
        "A product-local DesignRun kind appeared in the frontend; the loop "
        "mints canonical Goal/CreativeBrief/Run records only (#988): "
        f"{offenders}"
    )


def test_no_client_persist_system_of_record_for_loop_objects() -> None:
    offenders: list[str] = []
    for path in _frontend_sources():
        text = path.read_text(encoding="utf-8")
        for key in STORAGE_KEY_RE.findall(text):
            if FORBIDDEN_KEY_WORD_RE.search(key):
                offenders.append(f"{path.relative_to(_PACKAGES)}: {key}")
    assert not offenders, (
        "Loop state moved into client storage; the loop's ids are restored "
        "from the canonical APIs after refresh, never from a client store "
        f"(#988): {offenders}"
    )


def test_no_pack_specific_route_and_no_atelier_page() -> None:
    app = (_FRONTEND_SRC / "App.tsx").read_text(encoding="utf-8")
    offenders = [
        path for path in ROUTE_PATH_RE.findall(app) if FORBIDDEN_ROUTE_SEGMENT_RE.search(path)
    ]
    assert not offenders, (
        "A pack (or Studio variant) became a route — a product identity; "
        f"packs are bindings on the Run, never routes (#793/#988): {offenders}"
    )
    atelier = [str(path.relative_to(_PACKAGES)) for path in _FRONTEND_SRC.rglob("Atelier*.tsx")]
    assert not atelier, f"A second Studio page appeared (#988): {atelier}"
