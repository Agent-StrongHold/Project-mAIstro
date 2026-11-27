"""In-process proof for the Conductor API/UI permission-matrix gate (#336).

The gate runs as a quality.yml step (`Conductor API/UI permission matrix`),
but a workflow step records no coverage and the diff gate scores `scripts/`
files — a gate whose own logic is unmeasured is exactly the hole #257 closed
for the rest of `scripts/`. This module drives the script in process: the
shipped tree passes with the middleware table generated from the one policy
source, and each drift direction (middleware table edited by hand, a UI
action the frontend never shipped, an action absent from the API policy) is
refused with its specific failure named.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-conductor-permission-matrix.py"

spec = importlib.util.spec_from_file_location("_check_conductor_permission_matrix", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_shipped_tree_passes_with_one_policy_source(capsys) -> None:
    """The real tree satisfies the matrix, and the OK line says what it proved."""
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "permission matrix OK" in out
    # The gate's whole point, stated directly: the middleware's protected-op
    # table is generated from permission_policy, not a second hand-written one.
    assert mod.protected_ops_by_method() == mod._PROTECTED_OPS


def test_a_hand_edited_middleware_table_is_refused(monkeypatch, capsys) -> None:
    """Deleting an entry from the middleware table fails the gate, not silently."""
    drifted = {method: dict(paths) for method, paths in mod._PROTECTED_OPS.items()}
    del drifted["POST"]["/v1/settings"]
    monkeypatch.setattr(mod, "_PROTECTED_OPS", drifted)

    assert mod.main() == 1
    assert "not generated from permission_policy" in capsys.readouterr().err


def test_a_ui_action_the_frontend_never_shipped_is_refused(monkeypatch, capsys) -> None:
    """A policy row with no reachable control fails all three drift checks.

    The synthetic action names a path and permission no frontend source
    references and no API policy entry protects, so the gate names the
    unadvertised control instead of letting it become a guaranteed 403.
    """
    from services.permission_policy import ProtectedOperation

    ghost = ProtectedOperation(
        "PUT", "/v1/nonexistent/{id}", "tests.nonexistent", "a control the UI never shipped"
    )
    monkeypatch.setattr(mod, "UI_MUTATIONS", (*mod.UI_MUTATIONS, ghost))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "does not reference '/v1/nonexistent/'" in err
    assert "does not name 'tests.nonexistent'" in err
    assert "absent from the API policy" in err


def test_frontend_sources_scan_pages_and_lib_modules(monkeypatch, tmp_path) -> None:
    """The scan follows the #2273 restructure: pages and lib modules, no api/.

    The lib/ half is a real branch of the scan (the attention doors live in
    lib modules now), and a frontend tree without lib/ must scan to empty
    rather than crash — both arcs are exercised here.
    """
    (tmp_path / "lib").mkdir()
    (tmp_path / "Pages.tsx").write_text("page source", encoding="utf-8")
    (tmp_path / "lib" / "helpers.ts").write_text("helper source", encoding="utf-8")
    monkeypatch.setattr(mod, "FRONTEND", tmp_path)
    assert mod._frontend_sources() == ["page source", "helper source"]

    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.setattr(mod, "FRONTEND", bare)
    assert mod._frontend_sources() == []
