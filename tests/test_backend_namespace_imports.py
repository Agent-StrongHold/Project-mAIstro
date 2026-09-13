from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_both_backend_asgi_namespaces_coexist() -> None:
    """Import authority stays qualified when both applications share a process."""
    env = os.environ | {
        "PYTHONPATH": os.pathsep.join(
            (
                str(ROOT / "packages" / "hive-conductor" / "backend"),
                str(ROOT / "packages" / "maistro-turing" / "backend"),
                str(ROOT / "packages" / "maistro-core" / "src"),
                str(ROOT / "packages" / "maistro-turing" / "src"),
            )
        ),
        "TURING_SERVICE_KEY": "test-turing-service-key",
        "SESSION_COOKIE_SECURE": "false",
        "ALLOW_INSECURE_TRANSPORT": "true",
        "REQUIRE_AUTH": "false",
    }
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, sys; "
            "mods = ('hive_conductor.main', 'hive_conductor.routes.health', "
            "'hive_conductor.middleware.auth', 'maistro_turing_backend.main', "
            "'maistro_turing_backend.routes.health', 'maistro_turing_backend.middleware.auth'); "
            "[importlib.import_module(name) for name in mods]; "
            "assert not {'main', 'routes', 'middleware', 'config', 'state'} & sys.modules.keys()",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
