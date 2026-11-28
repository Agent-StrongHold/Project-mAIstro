#!/usr/bin/env python3
"""Check that the Conductor API and UI use one permission inventory."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "packages" / "hive-conductor" / "backend"
FRONTEND = ROOT / "packages" / "hive-conductor" / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

from middleware.auth import _PROTECTED_OPS  # noqa: E402
from services.permission_policy import (  # noqa: E402
    PROTECTED_OPERATIONS,
    UI_MUTATIONS,
    protected_ops_by_method,
)


def _frontend_sources() -> list[str]:
    """Concatenate the hand-written frontend sources the UI contract names.

    The #2273 restructure moved mutation helpers out of page components into
    lib modules (e.g. lib/attention.ts posts the optimizer proposal doors),
    so the scan follows both .tsx pages and lib/*.ts. Generated API types
    (src/api/) are excluded on purpose: a generated schema naming a route or
    permission is not a shipped control, and letting it satisfy the scan
    would mask a removed action.
    """
    paths = list(FRONTEND.rglob("*.tsx"))
    lib = FRONTEND / "lib"
    if lib.is_dir():
        paths.extend(lib.glob("*.ts"))
    return [path.read_text(encoding="utf-8") for path in paths]


def main() -> int:
    expected = protected_ops_by_method()
    if expected != _PROTECTED_OPS:
        print(
            "Conductor middleware policy is not generated from permission_policy", file=sys.stderr
        )
        return 1

    frontend = "\n".join(_frontend_sources())
    failures: list[str] = []
    for operation in UI_MUTATIONS:
        # Route parameters are represented by template expressions in TSX;
        # checking the stable prefix catches a removed control without trying
        # to parse TypeScript.
        stable_path = operation.path.split("{")[0]
        if stable_path not in frontend:
            failures.append(f"UI action {operation.action!r} does not reference {stable_path!r}")
        if operation.permission not in frontend:
            failures.append(
                f"UI action {operation.action!r} does not name {operation.permission!r}"
            )

    for operation in UI_MUTATIONS:
        stable_path = operation.path.split("{")[0]
        if not any(
            item.method == operation.method
            and item.permission == operation.permission
            and (stable_path.startswith(item.path) or item.path.startswith(stable_path))
            for item in PROTECTED_OPERATIONS
        ):
            failures.append(f"UI action {operation.action!r} is absent from the API policy")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        f"permission matrix OK: {len(PROTECTED_OPERATIONS)} API entries, {len(UI_MUTATIONS)} UI mutations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
