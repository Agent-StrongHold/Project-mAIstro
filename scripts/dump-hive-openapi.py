#!/usr/bin/env python3
"""Write the hive-conductor backend's OpenAPI document, byte-for-byte reproducible (#1048).

The frontend's entity types are generated from this document by
`openapi-typescript` (`npm run gen:api` in `packages/hive-conductor/frontend`)
into `src/api/types.gen.ts`, which is committed. CI regenerates both and fails
on any diff, so a backend schema change that the frontend has not picked up is
a red build rather than an `undefined` at runtime.

Reproducible means the same source tree gives the same bytes on every machine:
keys sorted, fixed indentation, trailing newline. The app is imported rather
than parsed, the same way `check-frontend-api-routes.py` reads its route table.

Why a degraded app is refused
-----------------------------
Four routers are optional and mounted inside a `try`, so a missing dependency
drops their routes, and their schemas, without an error. A document built from
that app would delete those types from `types.gen.ts`, and the drift check
would then report the environment rather than the code. So any failure
recorded on `app.state.optional_routers` stops the dump.

Usage
-----
    uv run python scripts/dump-hive-openapi.py [OUTPUT]

OUTPUT defaults to `packages/hive-conductor/frontend/openapi.json` (gitignored).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "packages" / "hive-conductor" / "backend"
DEFAULT_OUTPUT = REPO_ROOT / "packages" / "hive-conductor" / "frontend" / "openapi.json"


def render(document: dict[str, Any]) -> str:
    """The document as text that depends only on its content."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def import_paths() -> list[Path]:
    """What the app needs on `sys.path`, nearest-first.

    BACKEND is last in the list and therefore first on the path: the monorepo
    root also has a `services/` package that shadows the app's own when it wins
    the race (see `check-frontend-api-routes.py`).
    """
    return [*sorted(REPO_ROOT.glob("packages/*/src")), BACKEND]


def build_document() -> tuple[dict[str, Any], list[str]]:
    """The app's OpenAPI document, and any optional router that failed to load."""
    for entry in import_paths():
        if str(entry) in sys.path:
            sys.path.remove(str(entry))
        sys.path.insert(0, str(entry))
    os.environ.setdefault("HIVE_SKIP_DOTENV", "1")
    # Imported here, not at module scope: building the app is the expensive part
    # and the tests exercise `render` without it.
    from main import app

    degraded = [
        f"{module}: {cause}"
        for module, cause in getattr(app.state, "optional_routers", {}).items()
        if cause is not None
    ]
    return app.openapi(), degraded


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    document, degraded = build_document()
    if degraded:
        print("FAIL: the app is missing optional routers, so its schema is incomplete\n")
        for entry in degraded:
            print(f"  optional router did not load -- {entry}")
        print("\nFix the import, then re-run; a partial document would delete their types.")
        return 1
    if not document.get("paths"):
        print("FAIL: the OpenAPI document has no paths; nothing was measured")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(document), encoding="utf-8")
    schemas = document.get("components", {}).get("schemas", {})
    print(f"ok: wrote {output} ({len(document['paths'])} paths, {len(schemas)} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
