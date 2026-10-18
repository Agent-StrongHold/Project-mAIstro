"""Tests for the Workspace cutover retirement ledger gate (#1046, cutover S0.1).

The ledger is only worth having if it cannot drift from the tree in either
direction: an entry claiming a deletion that did not happen, or a retiring
surface quietly picking up a new consumer, must both fail.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-workspace-retirement.py"
PAGES = "packages/hive-conductor/frontend/src/pages"
ROUTES = "packages/hive-conductor/backend/routes"
STORES = "packages/hive-conductor/backend/stores.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_workspace_retirement", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "kind": "page",
        "path": f"{PAGES}/Docs.tsx",
        "disposition": "RETIRE",
        "replaced_by": None,
        "delete_by": "M3",
        "owner": "#1046",
    }
    entry.update(overrides)
    return entry


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    _write(tmp_path, f"{PAGES}/Docs.tsx", "export default function Docs() {}\n")
    _write(tmp_path, f"{ROUTES}/memory.py", "router = None\n")
    _write(tmp_path, STORES, "dag_runs: dict[str, object] = {}\n")
    return tmp_path


def test_the_ledger_matches_the_current_repository(gate) -> None:
    ledger = json.loads(gate.LEDGER.read_text())

    assert gate.check(ledger, ROOT) == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"disposition": "DEPRECATE"}, "disposition 'DEPRECATE'"),
        ({"kind": "widget"}, "kind 'widget'"),
        ({"owner": "1046"}, "owner must be an issue reference"),
        ({"delete_by": None}, "needs a delete_by milestone"),
        ({"disposition": "KEEP", "delete_by": "M3"}, "a KEEP entry has no delete_by"),
        ({"kind": "store", "path": STORES}, "'<stores.py path>::<name>'"),
    ],
)
def test_malformed_entries_are_rejected(gate, tree: Path, overrides, message) -> None:
    failures = gate.check({"entries": [_entry(**overrides)]}, tree)

    assert any(message in failure for failure in failures), failures


def test_a_missing_required_field_is_rejected(gate, tree: Path) -> None:
    entry = _entry()
    del entry["replaced_by"]

    assert gate.check({"entries": [entry]}, tree) == [
        f"entry 0 ({PAGES}/Docs.tsx): missing 'replaced_by'"
    ]


def test_an_entry_marked_deleted_whose_file_remains_fails(gate, tree: Path) -> None:
    failures = gate.check({"entries": [_entry(deleted=True)]}, tree)

    assert failures == [f"{PAGES}/Docs.tsx: marked deleted but still present"]


def test_a_deleted_store_must_be_gone_from_stores_py(gate, tree: Path) -> None:
    live = _entry(kind="store", path=f"{STORES}::dag_runs", deleted=True)
    gone = _entry(kind="store", path=f"{STORES}::missions", deleted=True)

    assert gate.check({"entries": [live, gone]}, tree) == [
        f"{STORES}::dag_runs: marked deleted but still present"
    ]


def test_a_live_entry_whose_asset_is_missing_fails(gate, tree: Path) -> None:
    failures = gate.check({"entries": [_entry(path=f"{PAGES}/Gone.tsx")]}, tree)

    assert failures == [
        f"{PAGES}/Gone.tsx: not found; delete the entry's asset and mark it deleted"
    ]


def test_new_importers_of_a_retiring_page_router_or_store_fail(gate, tree: Path) -> None:
    _write(tree, "packages/hive-conductor/frontend/src/Home.tsx", 'import D from "./pages/Docs";\n')
    _write(tree, "packages/hive-conductor/backend/main.py", "from routes import memory\n")
    _write(
        tree, "packages/hive-conductor/backend/services/x.py", "import stores\nstores.dag_runs\n"
    )
    _write(tree, "packages/hive-conductor/backend/tests/test_x.py", "from routes import memory\n")
    entries = [
        _entry(),
        _entry(kind="router", path=f"{ROUTES}/memory.py", disposition="PROJECT"),
        _entry(kind="store", path=f"{STORES}::dag_runs"),
    ]

    failures = gate.check({"entries": entries}, tree)

    assert sorted(failures) == sorted(
        [
            f"{PAGES}/Docs.tsx: NEW importer packages/hive-conductor/frontend/src/Home.tsx"
            " -- a retiring surface may not gain consumers",
            f"{ROUTES}/memory.py: NEW importer packages/hive-conductor/backend/main.py"
            " -- a retiring surface may not gain consumers",
            f"{STORES}::dag_runs: NEW importer packages/hive-conductor/backend/services/x.py"
            " -- a retiring surface may not gain consumers",
        ]
    )


def test_a_recorded_importer_that_stopped_importing_must_be_pruned(gate, tree: Path) -> None:
    stale = "packages/hive-conductor/frontend/src/App.tsx"
    _write(tree, stale, "export {};\n")

    failures = gate.check({"entries": [_entry(importers=[stale])]}, tree)

    assert failures == [f"{PAGES}/Docs.tsx: {stale} no longer imports it; prune it from importers"]


def test_keep_entries_may_be_imported_freely(gate, tree: Path) -> None:
    _write(tree, "packages/hive-conductor/frontend/src/App.tsx", 'import D from "./pages/Docs";\n')
    keep = _entry(disposition="KEEP", delete_by=None)

    assert gate.check({"entries": [keep]}, tree) == []


def _ledger(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"entries": list(entries)}


def test_an_importer_the_trusted_base_did_not_list_needs_a_landed_grant(gate) -> None:
    app = "packages/hive-conductor/frontend/src/App.tsx"
    trusted = _ledger(_entry())
    candidate = _ledger(_entry(importers=[app]))
    key = f"{PAGES}/Docs.tsx::{app}"
    assert gate.provenance_failures(candidate, trusted, set()) == [
        f"{key}: NEW tolerated importer absent from the trusted base and not previously authorized"
    ]
    assert gate.provenance_failures(candidate, trusted, {key}) == []
    assert gate.provenance_failures(candidate, candidate, set()) == []


def test_dropping_or_keeping_a_tracked_entry_needs_a_landed_grant(gate) -> None:
    trusted = _ledger(_entry())
    path = f"{PAGES}/Docs.tsx"
    for candidate in (_ledger(), _ledger(_entry(disposition="KEEP", delete_by=None))):
        [failure] = gate.provenance_failures(candidate, trusted, set())
        assert failure.startswith(f"{path}: tracked at the trusted base")
        assert gate.provenance_failures(candidate, trusted, {f"untrack::{path}"}) == []


def test_a_store_missing_from_the_ledger_fails(gate, tree: Path) -> None:
    _write(
        tree,
        STORES,
        "known = JsonStore('known')\nunknown = JsonStore('unknown')\n",
    )
    failures = gate.check({"entries": [_entry(kind="store", path=f"{STORES}::known")]}, tree)

    assert failures == [
        f"{STORES}::unknown: store exists in stores.py but is absent from the ledger"
    ]


def test_stores_module_aliases_are_tracked(gate, tree: Path) -> None:
    _write(tree, STORES, "dag_runs = JsonStore('dag_runs')\n")
    _write(
        tree,
        "packages/hive-conductor/backend/services/x.py",
        "import stores as legacy\nlegacy.dag_runs\n",
    )

    failures = gate.check({"entries": [_entry(kind="store", path=f"{STORES}::dag_runs")]}, tree)

    assert failures == [
        f"{STORES}::dag_runs: NEW importer packages/hive-conductor/backend/services/x.py"
        " -- a retiring surface may not gain consumers"
    ]


def test_a_new_importer_cannot_be_self_authorized_in_the_candidate_ledger(gate, tree: Path) -> None:
    app = "packages/hive-conductor/frontend/src/App.tsx"
    _write(tree, app, 'import D from "./pages/Docs";\n')
    trusted = _ledger(_entry())
    candidate = _ledger(_entry(importers=[app]))

    failures = gate.check(candidate, tree, trusted=trusted)

    assert failures == [
        f"{PAGES}/Docs.tsx: NEW importer {app} -- a retiring surface may not gain consumers"
    ]
