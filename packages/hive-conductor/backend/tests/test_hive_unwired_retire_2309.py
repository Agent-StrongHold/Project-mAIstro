"""#2309 — hive CONNECT leftovers stay RETIREd for Workspaces v1.0."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DISPOSITIONS = _REPO_ROOT / "quality" / "reachability-dispositions.json"

_GROUPS = {
    # `services.entra_entitlements` is intentionally absent: the #492 JIT lane
    # wires it (Settings validation + `EntraJitProvisioner`), so on this tree
    # it is reachable and must not be pinned into the RETIRE group.
    "hive-unwired-services": {
        "@flat/hive-conductor/services.canonical_corpus",
        "@flat/hive-conductor/services.chatbot_integration",
        "@flat/hive-conductor/services.eval_bootstrap",
        "@flat/hive-conductor/services.preference_calibration",
    },
    "hive-pg-persistence": {
        "@flat/hive-conductor/services.pg_persisted",
    },
    "hive-dag-and-artifact-optimisation": {
        "@flat/hive-conductor/services.hill_climber",
        "@flat/hive-conductor/services.skill_optimizer",
        "@flat/hive-conductor/services.ui_auto_climb",
        "@flat/hive-conductor/services.ui_climb_vm",
        "@flat/hive-conductor/services.ui_hill_climber",
    },
}


def test_hive_connect_leftovers_retired_with_replaced_by() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    by_id = {g["id"]: g for g in payload["groups"]}
    for group_id, modules in _GROUPS.items():
        group = by_id[group_id]
        assert group["disposition"] == "RETIRE", group_id
        assert set(group["modules"]) == modules, group_id
        assert group.get("replaced_by"), group_id
        assert "root" not in group, group_id
        assert "2309" in str(group["rationale"]), group_id
