#!/usr/bin/env python3
"""Gate: design explore/judge egress stays on the governed Invocation path.

M7-A11 freezes the seam, not just the current code:

1. **No provider SDK imports anywhere under ``packages/maistro-design``.**
   Design reaches models only through maistro-core's governed
   ``Capability -> Provider -> Binding -> Invocation`` egress
   (ADR-081226-6b46); an ``openai``/``litellm``/... import in the package is a
   competing egress by construction.

2. **No raw model-completion HTTP inside the package.** A
   ``chat/completions``-style endpoint fragment combined with an HTTP call
   (``post``/``stream``/``send``/``request``) is the shape of a private
   director LLM; DesignEngine assembling prompt stacks (ADR-061) never has
   either.

3. **Design Studio pages never talk to a model host from the browser.** Pages
   speak to the Hive API through ``apiGet``/``apiPost``. DeckBuilder's
   pre-existing in-editor chat — a caller of the governed Hive chat admission
   (``/v1/chat/complete``), not a design path — is recorded ratchet-style: it
   may not grow, and any other page or second occurrence fails.

A candidate may not approve an escape by editing this gate; the baseline lives
in this file next to the rule that enforces it, and expansions are judged in
review against the merge-base inventory.

Usage:
    python3 scripts/check-design-model-egress.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_SRC = ROOT / "packages" / "maistro-design" / "src" / "maistro_design"
FRONTEND_PAGES = ROOT / "packages" / "hive-conductor" / "frontend" / "src" / "pages"

FORBIDDEN_PROVIDER_ROOTS = frozenset(
    {
        "openai",
        "anthropic",
        "litellm",
        "cohere",
        "google",
        "xai",
        "dashscope",
        "mistralai",
    }
)

EGRESS_ENDPOINT_FRAGMENTS = ("chat/completions", "/completions", "/v1/responses")
HTTP_CALL_ATTRS = frozenset({"post", "stream", "send", "request"})

MODEL_HOST_MARKERS = (
    "chat/completions",
    "/completions",
    "api.openai.com",
    "api.x.ai",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
)
BARE_EGRESS_MARKERS = ("XMLHttpRequest", "EventSource(", "axios", "fetch(")

#: Ratchet baseline: (page, marker) -> permitted occurrence count. DeckBuilder's
#: slide assistant is the one recorded caller of the governed Hive chat
#: admission on a Design Studio surface; it is a Hive chat surface, not a
#: design explore/judge path, and it must never become one.
RAW_COMPLETION_BASELINE: dict[tuple[str, str], int] = {
    ("DeckBuilder.tsx", "/v1/chat/complete"): 1,
    ("DeckBuilder.tsx", "fetch("): 1,
}

DESIGN_STUDIO_PAGES = (
    "DesignStudio.tsx",
    "FixedPageEditor.tsx",
    "FixedPageArtifactEditor.tsx",
    "DeckBuilder.tsx",
)


def _imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _performs_model_egress(tree: ast.AST, source: str) -> bool:
    if not any(fragment in source for fragment in EGRESS_ENDPOINT_FRAGMENTS):
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in HTTP_CALL_ATTRS
        for node in ast.walk(tree)
    )


def _check_python_sources() -> list[str]:
    failures: list[str] = []
    for path in sorted(DESIGN_SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for imported in _imported_modules(tree):
            root = imported.split(".")[0]
            if root in FORBIDDEN_PROVIDER_ROOTS:
                failures.append(f"{path.relative_to(ROOT)}: provider SDK import {imported!r}")
        if _performs_model_egress(tree, source):
            failures.append(f"{path.relative_to(ROOT)}: raw model-completion HTTP call")
    return failures


def _check_frontend_pages() -> list[str]:
    failures: list[str] = []
    for name in DESIGN_STUDIO_PAGES:
        page = FRONTEND_PAGES / name
        if not page.exists():
            failures.append(f"Design Studio page {name!r} is missing; update this gate")
            continue
        source = page.read_text(encoding="utf-8")
        for marker in (*MODEL_HOST_MARKERS, *BARE_EGRESS_MARKERS):
            count = source.count(marker)
            allowed = RAW_COMPLETION_BASELINE.get((name, marker), 0)
            if count > allowed:
                failures.append(
                    f"frontend/src/pages/{name}: {marker!r} occurs {count}x "
                    f"(baseline allows {allowed})"
                )
    return failures


def main() -> int:
    failures = [*_check_python_sources(), *_check_frontend_pages()]
    for failure in failures:
        print(f"DESIGN-MODEL-EGRESS: {failure}")
    if failures:
        print(
            "\nDesign model egress must cross maistro-core's governed "
            "Capability -> Provider -> Binding -> Invocation path "
            "(ADR-081226-6b46, M7-A11). DesignEngine does not call a model "
            "(ADR-061), and Design Studio pages do not talk to model hosts."
        )
        return 1
    print(
        "design model egress: ok — "
        f"{len(list(DESIGN_SRC.rglob('*.py')))} python modules and "
        f"{len(DESIGN_STUDIO_PAGES)} Design Studio pages checked"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
