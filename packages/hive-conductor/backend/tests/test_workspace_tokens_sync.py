"""The frontend's copy of the Workspace tokens is the bundled design system, byte for byte.

`frontend/src/themes/workspace-tokens.css` exists because Vite bundles from
the frontend tree and the design system lives in `maistro-design`. A copy
that drifts is a second design system nobody decided on (ADR-091626-ba4f), so
this holds the two identical; the bridge next to it is where the app is
allowed to differ, and it says why.
"""

from __future__ import annotations

from pathlib import Path

_PACKAGES = Path(__file__).resolve().parents[3]
_BUNDLE = _PACKAGES / "maistro-design/src/maistro_design/systems/bundled/workspace/tokens.css"
_COPY = _PACKAGES / "hive-conductor/frontend/src/themes/workspace-tokens.css"


def test_the_frontend_tokens_are_the_bundled_tokens() -> None:
    assert _COPY.read_bytes() == _BUNDLE.read_bytes(), (
        "frontend/src/themes/workspace-tokens.css drifted from the bundled "
        "workspace design system; copy the bundle over it (the bridge file is "
        "where the app may differ)"
    )


def test_the_bridge_binds_the_shipped_faces_and_nothing_else_redeclares_a_token() -> None:
    """The bridge may rebind `--font-*` to the fontsource "Variable" family
    names and alias the old Conductor names; it must not redefine a colour or
    size token, and no other stylesheet may declare one either."""
    import re

    bridge = (_PACKAGES / "hive-conductor/frontend/src/themes/workspace-bridge.css").read_text(
        encoding="utf-8"
    )
    tokens = set(re.findall(r"^\s+(--[a-z0-9-]+):", _BUNDLE.read_text(encoding="utf-8"), re.M))
    declared_in_bridge = set(re.findall(r"^\s+(--[a-z0-9-]+):", bridge, re.M))
    assert declared_in_bridge & tokens == {"--font-display", "--font-body", "--font-mono"}

    src = _PACKAGES / "hive-conductor/frontend/src"
    for path in src.rglob("*.css"):
        if path.name in {"workspace-tokens.css", "workspace-bridge.css"}:
            continue
        redeclared = set(re.findall(r"^\s+(--[a-z0-9-]+):", path.read_text(encoding="utf-8"), re.M))
        assert not (redeclared & tokens), f"{path.name} redeclares {sorted(redeclared & tokens)}"
