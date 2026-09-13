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


def test_turing_documented_backend_command_starts_from_backend_directory() -> None:
    """Exercise the shipped uvicorn command, not only importlib discovery."""
    backend = ROOT / "packages" / "maistro-turing" / "backend"
    env = os.environ | {
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT / "packages" / "maistro-turing" / "src"), os.environ.get("PYTHONPATH", ""))
        ),
        "TURING_SERVICE_KEY": "test-turing-service-key",
        "TURING_ALLOW_INSECURE_TRANSPORT": "1",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "maistro_turing_backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--log-level",
            "error",
        ],
        cwd=backend,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        try:
            returncode = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            returncode = None
        if returncode is not None:
            _stdout, stderr = process.communicate()
            raise AssertionError(f"Turing backend exited during startup: {stderr}")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
