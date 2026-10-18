"""Importing the server app must not require the optional tool-server stack.

The CI hive-conductor step runs the #1057 two-user E2E
(``test_production_workspace_scope.py::test_shared_bridge_keeps_two_
authenticated_user_tasks_isolated``) in an interpreter built from hive's lean
``requirements.txt``, which deliberately does not carry maistro-core's
``[llm]`` extra — fastmcp among it. For a while ``maistro_server.main``
pulled the sandbox MCP server (and with it fastmcp) at module scope, so that
import failed with ``ModuleNotFoundError`` and the E2E went red in exactly
one CI job while every workspace-venv run stayed green.

The cleanup import is lazy now, and degrades to a no-op when the extra is
absent: a missing sandbox stack means no sandbox containers exist, so there
is nothing to tear down. This test pins that contract in the rich environment
too, by blocking ``fastmcp`` resolution in a clean subprocess and importing
the app — the same shape the lean CI interpreter produces.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

_BLOCK_FASTMCP = textwrap.dedent(
    '''\
    import sys


    class _LeanInstall:
        """Simulate an environment without maistro-core's ``[llm]`` extra."""

        def find_spec(self, fullname, path=None, target=None):
            if fullname == "fastmcp" or fullname.startswith("fastmcp."):
                raise ModuleNotFoundError(f"No module named {fullname!r} (lean install)")
            return None


    sys.meta_path.insert(0, _LeanInstall())
    '''
)


def test_importing_the_app_does_not_require_the_llm_extra() -> None:
    # The suite imports resolve through pytest's ``pythonpath`` ini; a bare
    # subprocess has to be handed the same roots explicitly.
    repo_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(repo_root / "packages" / "maistro-core" / "src"),
            str(repo_root / "packages" / "maistro-server" / "src"),
            env.get("PYTHONPATH", ""),
        )
    )
    env.setdefault("MAISTRO_DRY_RUN", "1")
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCK_FASTMCP + "import maistro_server.main\n"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert completed.returncode == 0, (
        f"importing maistro_server.main dragged in an optional extra:\n{completed.stderr}"
    )
