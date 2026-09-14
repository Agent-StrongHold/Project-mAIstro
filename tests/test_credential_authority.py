"""The credential authority has one owner per responsibility (#1186)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "credential-authority.json"

# Protocol-shaped interfaces are not stores. The core store is the only
# production implementation permitted to own encrypted user credentials.
_ALLOWED_STORE_CLASSES = {
    ("packages/maistro-core/src/maistro/credentials/store.py", "UserCredentialStore"),
    ("packages/hive-conductor/backend/services/tool_primitives.py", "CredentialStore"),
}


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for path in (ROOT / "packages").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if "tests" in path.parts or path.name.startswith("test_"):
            continue
        if relative.startswith("packages/hive-conductor/cage/"):
            continue
        files.append(path)
    return files


def _unscoped_store_implementations() -> list[str]:
    findings: set[str] = set()
    for path in _production_python_files():
        relative = path.relative_to(ROOT).as_posix()
        if "credential_store" in path.stem.lower():
            findings.add(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = node.name.lower()
            if (
                "credential" in name
                and "store" in name
                and not name.endswith(("error", "unavailable"))
            ):
                identity = (relative, node.name)
                if identity not in _ALLOWED_STORE_CLASSES:
                    findings.add(f"{relative}::{node.name}")
    return sorted(findings)


def test_credential_authority_ledger_records_live_and_retired_surfaces() -> None:
    ledger = _ledger()
    canonical = ledger["canonical"]
    retired = ledger["retired"]

    assert Path(ROOT / canonical["product_crud"]).is_file()
    store_path, store_class = canonical["encrypted_store"].split("::", 1)
    assert store_class == "UserCredentialStore"
    assert Path(ROOT / store_path).is_file()
    assert canonical["runtime_selection"].startswith(
        "packages/maistro-core/src/maistro/credentials/router.py::"
    )
    assert retired == [
        {
            "path": "packages/hive-conductor/backend/services/credential_store_v2.py",
            "disposition": "RETIRE",
            "replacement": "services.user_credentials -> maistro.credentials.store.UserCredentialStore",
            "reason": "The v2 PostgREST service exposed id-only reads, secret reads, updates, and deletes without a principal predicate. It had no production callers and is deleted rather than made into a second credential authority.",
            "issue": "#1186",
        }
    ]
    assert not (ROOT / retired[0]["path"]).exists()


def test_no_second_production_credential_store_can_be_added() -> None:
    """A store implementation must be scoped and use the canonical authority."""
    assert _unscoped_store_implementations() == []
