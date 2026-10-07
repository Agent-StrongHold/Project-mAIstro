"""The sandbox substrate and the extension host import in any order.

`maistro.sandbox.protocol` used to bind `SandboxFence` at module scope, and
`maistro.sandbox.fence` reaches `maistro.runs.model`, whose package __init__
imports `execution`, which wires `maistro.runtime` -> `maistro.extensions` ->
`maistro.extensions.isolation` -> `maistro.sandbox.protocol`. The cycle was
invisible while every caller imported `maistro.extensions` (or anything that
pulled the runs spine) first — but `import maistro.sandbox` on its own, as the
ambient-credential surface (#964's `credential_boundary`) does, died with
"cannot import name 'SandboxFence' from partially initialized module".

These run in subprocesses on purpose: within one interpreter the first test to
touch any of the packages populates `sys.modules` and every later import order
looks fine regardless of the defect. Same method as tests/runs/test_import_order.py.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

import maistro

#: The subprocesses must find the package under test whether or not the parent
#: run set PYTHONPATH, so derive it from the imported package rather than trust
#: the ambient environment.
_SRC = str(pathlib.Path(maistro.__file__).resolve().parent.parent)


def _run(statement: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([_SRC, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


ORDERS = [
    # The order that used to die: the sandbox package is the entry point, so
    # `fence` starts loading before `maistro.extensions` re-imports the
    # isolation layer that reads `maistro.sandbox.protocol`.
    "import maistro.sandbox",
    "from maistro.sandbox.credential_boundary import candidate_env",
    "import maistro.sandbox.protocol",
    # The orders that always worked and must keep working.
    "import maistro.extensions",
    "import maistro.extensions.isolation",
    "import maistro.runs",
]


@pytest.mark.parametrize("statement", ORDERS)
def test_each_entry_point_imports_first(statement: str) -> None:
    result = _run(statement)

    assert result.returncode == 0, result.stderr


def test_the_deferred_import_did_not_cost_the_config_its_shape() -> None:
    """`SandboxFence` moved under TYPE_CHECKING; the dataclass must not care."""
    statement = (
        "from dataclasses import fields\n"
        "from maistro.sandbox.protocol import SandboxConfig\n"
        "config = SandboxConfig(memory_mb=64, max_file_mb=8)\n"
        "assert config.memory_mb == 64\n"
        "names = [f.name for f in fields(SandboxConfig)]\n"
        "assert 'fence' in names, names\n"
        "import maistro.extensions.isolation as iso\n"
        "assert hasattr(iso, 'ExtensionSandboxRunner')\n"
    )
    result = _run(statement)

    assert result.returncode == 0, result.stderr
