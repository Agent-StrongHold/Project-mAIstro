"""Architecture fitness: one HTTP principal type (Workspace cutover P0.1 / #53)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / "scripts" / "check-principal-identity.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_principal_identity", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_principal_importable_without_identity_extra() -> None:
    class _BlockRoot:
        def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
            if fullname.split(".")[0] == "bip_utils":
                raise ModuleNotFoundError("bip_utils")
            return None

    for name in list(sys.modules):
        if name.startswith("maistro.identity"):
            del sys.modules[name]
    sys.meta_path.insert(0, _BlockRoot())
    try:
        from maistro.identity import Principal
        from maistro.identity.principal import Principal as DirectPrincipal

        assert Principal is DirectPrincipal
        assert DirectPrincipal.from_legacy_dict({"id": "u1", "role": "admin"}).user_id == "u1"
    finally:
        sys.meta_path.pop(0)


def test_principal_identity_ratchet_has_no_new_violations() -> None:
    gate = _load_gate()
    new_violations, stale_keys, _ = gate.audit()
    assert not new_violations, "\n".join(item.key() for item in new_violations)
    assert not stale_keys, "\n".join(stale_keys)


@pytest.mark.ac
def test_principal_identity_gate_passes_in_ci() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
