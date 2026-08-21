"""Static boundary test (SPEC-226 / ADR-096).

Hive Conductor must not own a production TaskRunner — maistro-server is the
canonical backend. This scans the backend source tree for `TaskRunner`
imports outside the one place allowed to hold them: the demo-only
`LocalTaskBackend` inside adapters/task_backend.py.
"""

from __future__ import annotations

import pathlib

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
_ALLOWED = _BACKEND / "adapters" / "task_backend.py"


def _source_files() -> list[pathlib.Path]:
    files = []
    for path in _BACKEND.rglob("*.py"):
        if "tests" in path.relative_to(_BACKEND).parts:
            continue
        files.append(path)
    return files


def test_no_taskrunner_import_outside_local_backend() -> None:
    offenders = []
    for path in _source_files():
        if path == _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        if "TaskRunner" in text:
            offenders.append(str(path.relative_to(_BACKEND)))
    assert offenders == [], f"TaskRunner referenced outside LocalTaskBackend: {offenders}"


def test_local_backend_module_exists_and_holds_taskrunner() -> None:
    assert _ALLOWED.is_file(), "adapters/task_backend.py must exist"
    text = _ALLOWED.read_text(encoding="utf-8")
    assert "TaskRunner" in text
    assert "class LocalTaskBackend" in text
    assert "class MaistroServerTaskBackend" in text
