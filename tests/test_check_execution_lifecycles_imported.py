"""Imported extensions stay visible to the lifecycle ledger (#1136 / #1316)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gate():
    path = ROOT / "scripts" / "check-execution-lifecycles.py"
    spec = importlib.util.spec_from_file_location("_imported_lifecycle_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("imports", "expression", "origin"),
    [
        ("from .base import RunStatus", 'RunStatus | Literal["cancelled"]', ".base.RunStatus"),
        ("from pkg.base import RunStatus as RS", 'RS | Literal["cancelled"]', "pkg.base.RunStatus"),
        ("import pkg.base as b", 'b.RunStatus | Literal["cancelled"]', "pkg.base.RunStatus"),
        ("import pkg.base", 'pkg.base.RunStatus | Literal["cancelled"]', "pkg.base.RunStatus"),
        ("from . import base as b", 'b.RunStatus | Literal["cancelled"]', ".base.RunStatus"),
        (
            "from .base import RunStatus",
            'Optional[RunStatus | Literal["cancelled"]]',
            ".base.RunStatus",
        ),
        (
            "from .base import RunStatus",
            'Union[RunStatus, Literal["cancelled"]]',
            ".base.RunStatus",
        ),
        (
            "from .base import RunStatus",
            'Annotated[RunStatus | Literal["cancelled"], "hint"]',
            ".base.RunStatus",
        ),
    ],
)
@pytest.mark.parametrize("field", [False, True], ids=["alias", "field"])
def test_imported_extensions_require_an_independent_disposition(
    gate, imports: str, expression: str, origin: str, field: bool
) -> None:
    declaration = (
        f"class Worker:\n    status: {expression}" if field else f"WorkerStatus = {expression}"
    )
    source = f"from typing import Literal, Optional, Union, Annotated\n{imports}\n{declaration}\n"
    identity = "pkg.worker::Worker.status" if field else "pkg.worker::WorkerStatus"
    found = gate.work_state_literals(source, "pkg.worker")
    assert found == {identity: {"CANCELLED", f"<imported-type:{origin}>"}}
    assert any(identity in failure for failure in gate.audit({"lifecycles": {}}, found))
    assert gate._unauthorized_additions([identity], {}, set()) == [identity]


@pytest.mark.parametrize(
    "declaration",
    [
        "WorkerStatus = Optional[RunStatus]",
        'WorkerStatus = Annotated[RunStatus, Literal["cancelled"]]',
        'WorkerStatus = Annotated[int, RunStatus, Literal["queued", "running", "failed"]]',
        'WorkerStatus = RunStatus | Literal["red", "green"]',
        'ConfigurationValues = RunStatus | Literal["cancelled"]',
        'class Worker:\n    kind: RunStatus | Literal["cancelled"]',
        'WorkerStatus = Literal["queued", "running"]',
    ],
)
def test_unrelated_metadata_reuse_and_small_literals_remain_quiet(gate, declaration: str) -> None:
    source = (
        "from typing import Literal, Optional, Annotated\n"
        f"from .base import RunStatus\n{declaration}\n"
    )
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_helper_aliases_carry_import_evidence_and_preserve_scope(gate) -> None:
    source = """
from typing import Literal
from .base import RunStatus as RS
_Helper = RS
class A:
    Status = _Helper | Literal["cancelled"]
class B:
    RS = Literal["red", "green", "blue"]
    Status = RS | Literal["cancelled"]
class C:
    Status = _Helper | Literal["cancelled"]
"""
    evidence = {"CANCELLED", "<imported-type:.base.RunStatus>"}
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::A.Status": evidence,
        "pkg.worker::C.Status": evidence,
    }


def test_an_import_in_one_function_does_not_leak_into_its_sibling(gate) -> None:
    source = """
from typing import Literal
def a():
    from .base import RunStatus as RS
    WorkerStatus = RS | Literal["cancelled"]
def b():
    RS = Literal["red", "green", "blue"]
    WorkerStatus = RS | Literal["cancelled"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::a.WorkerStatus": {"CANCELLED", "<imported-type:.base.RunStatus>"}
    }


def test_named_imported_extension_is_reused_but_a_further_extension_is_visible(gate) -> None:
    source = """
from typing import Literal
from .base import RunStatus
WorkerStatus = RunStatus | Literal["cancelled"]
class Worker:
    status: WorkerStatus | None
    execution_status: WorkerStatus | Literal["failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::WorkerStatus": {"CANCELLED", "<imported-type:.base.RunStatus>"},
        "pkg.worker::Worker.execution_status": {
            "CANCELLED",
            "FAILED",
            "<imported-type:.base.RunStatus>",
        },
    }


def test_local_import_shadows_an_inherited_named_vocabulary(gate) -> None:
    source = """
from typing import Literal
RunStatus = Literal["queued", "running", "failed"]
class Worker:
    from .other import RunStatus
    status: RunStatus | Literal["failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::RunStatus": {"QUEUED", "RUNNING", "FAILED"},
        "pkg.worker::Worker.status": {"FAILED", "<imported-type:.other.RunStatus>"},
    }


def test_main_rejects_a_candidate_self_classified_imported_extension(
    gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Use the actual source scanner and trusted-source lookup, not a found-map mock."""
    source = tmp_path / "worker.py"
    original = "from typing import Literal\nfrom .base import RunStatus\n"
    source.write_text(original)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "worker.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "trusted source",
        ],
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    source.write_text(original + 'WorkerStatus = RunStatus | Literal["cancelled"]\n')
    identity = "pkg.worker::WorkerStatus"
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "lifecycles": {
                    identity: {
                        "classification": "CANONICAL",
                        "rationale": "candidate cannot grant itself authority",
                    }
                }
            }
        )
    )
    reach = SimpleNamespace(
        FLAT_APPS=(),
        _collect_modules=lambda: {"pkg.worker": source},
        _display_name=lambda key, _apps: key,
    )
    monkeypatch.setattr(gate, "_load_reachability", lambda: reach)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "LEDGER", ledger_path)
    baseline = SimpleNamespace(base_sha=revision, loads=lambda default=None: {"lifecycles": {}})
    provenance = SimpleNamespace(
        RatchetProvenanceError=RuntimeError,
        resolve_baseline=lambda *_a, **_k: baseline,
        require_measurement=lambda *_a, **_k: None,
        require_metric_version=lambda *_a, **_k: None,
        load_authorizations=lambda *_a, **_k: {},
        head_sha=lambda *_a: revision,
        Provenance=lambda **_k: SimpleNamespace(render=lambda: "fixture provenance"),
    )
    monkeypatch.setattr(gate, "_provenance", lambda: provenance)
    assert gate.main() == 1
    assert f"{identity}: NEW work-state vocabulary" in capsys.readouterr().out
    # Already-landed source is newly visible debt, not a candidate-only grant.
    subprocess.run(["git", "-C", str(tmp_path), "add", "worker.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "pre-existing extension",
        ],
        check=True,
    )
    baseline.base_sha = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    assert gate.main() == 0
