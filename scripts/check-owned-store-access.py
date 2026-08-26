#!/usr/bin/env python3
"""Gate: a store whose rows belong to a user is only reached through the view
that scopes it to that user (#312).

Why this exists rather than a code review note
----------------------------------------------
`stores.chat_sessions` is a module-level dict. Reading it in a handler is one
attribute access, it reads exactly like every other store access in the file,
and the resulting code is *correct in every respect except whose data it
returns*. Four handlers were written that way and each of them let any
authenticated user list, read, append to, or delete any other user's chat by
id. Nothing about the text of those handlers looked wrong.

`services/owned_records.OwnedStore` fixes the four. This fixes the fifth — the
one nobody has written yet. A new handler that reaches for the raw store fails
here, at the same moment it is written, instead of shipping.

What "owned" means
------------------
`OWNED_STORES` names the store attributes whose rows carry a `user_id`
identifying the person the row belongs to. A store is on this list because its
rows are *someone's*, not because it happens to have the field: `users` has a
user id and is not owned by anyone, so it is not here.

Add a store to `OWNED_STORES` when its model gains a real owner, and the gate
will tell you which handlers were reading it unscoped.

What is allowed to touch them
-----------------------------
- `stores.py` itself — it declares them.
- `services/owned_records.py` — it *is* the scoping view.
- test modules — a test that plants one user's row so another user can fail to
  read it has to reach the store directly to plant it.

Everything else — every module under `routes/` and every other module under
`services/` — goes through `OwnedStore`.

Usage
-----
    python3 scripts/check-owned-store-access.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "packages" / "hive-conductor" / "backend"

#: Store attributes on `stores` whose rows belong to an individual user.
OWNED_STORES: frozenset[str] = frozenset({"chat_sessions"})

#: Paths, relative to the backend root, that may name an owned store directly.
#: Each is here because it is either the declaration or the scoping seam —
#: never because scoping it was inconvenient.
ALLOWED: tuple[tuple[str, str], ...] = (
    ("stores.py", "declares the stores"),
    ("services/owned_records.py", "is the scoping view every other caller uses"),
)


def _is_test(relative: Path) -> bool:
    """Test modules plant rows for other users on purpose."""
    parts = relative.parts
    return "tests" in parts or relative.name.startswith("test_")


def _allowed(relative: Path) -> str | None:
    wanted = relative.as_posix()
    for path, reason in ALLOWED:
        if wanted == path:
            return reason
    return None


def direct_accesses(source: str, store_names: frozenset[str]) -> list[tuple[int, str]]:
    """`(line, store)` for every `stores.<owned>` in `source`.

    An attribute access on a name spelled `stores`, which is how the backend's
    flat module layout always refers to them (`import stores`). A local variable
    called `stores` would be a false positive; there is none, and one would be
    worth flagging anyway.
    """
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in store_names
            and isinstance(node.value, ast.Name)
            and node.value.id == "stores"
        ):
            found.append((node.lineno, node.attr))
    return found


def audit() -> list[str]:
    """One message per module that reaches an owned store directly."""
    failures: list[str] = []
    for path in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(BACKEND)
        if _is_test(relative) or _allowed(relative):
            continue
        for line, store in direct_accesses(path.read_text(encoding="utf-8"), OWNED_STORES):
            failures.append(
                f"  {relative.as_posix()}:{line}: reads stores.{store} directly — "
                f"use services.owned_records.OwnedStore so the access is scoped "
                f"to the authenticated user"
            )
    return failures


def main() -> int:
    if not BACKEND.is_dir():
        print(f"FAIL: {BACKEND} does not exist", file=sys.stderr)
        return 1

    failures = audit()
    if failures:
        print(f"FAIL: {len(failures)} unscoped access(es) to an owned store:\n")
        print("\n".join(failures))
        print(
            "\nAn unscoped read is not a bug you can see by reading the handler: "
            "\nit does the right thing to the wrong person's rows. Scope it, or "
            "\nadd the module to ALLOWED with the reason it cannot be scoped."
        )
        return 1

    owned = ", ".join(sorted(OWNED_STORES))
    print(f"ok: every access to {owned} goes through OwnedStore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
