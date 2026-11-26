"""Tests for the foreign-harness egress gate (issue #1613, M1-D).

The gate must fail a product module that references OpenClaw/Pi *and* performs
its own transport call (the raw side door #1613 forbids), while leaving the
Provider boundary, non-transport calls, and ambiguous names (``dict.get``,
``asyncio.run``) alone. Detection is exercised on synthetic trees so tests stay
hermetic; the real-checkout test proves the shipped tree is clean.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-foreign-harness-egress.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_foreign_harness_egress", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VIA_HTTPX = '''
import httpx

async def call_openclaw(prompt: str) -> dict:
    """Send one task straight to the OpenClaw gateway."""
    async with httpx.AsyncClient() as client:
        return await client.post("http://gateway:3000/api", json={"message": prompt})
'''

VIA_LOCAL_CLIENT = """
import httpx

async def run_openclaw_task(client: httpx.AsyncClient, task: str) -> None:
    await client.post("http://openclaw-gateway/rpc", json={"task": task})
"""

VIA_SUBPROCESS = '''
import subprocess

def run_pi_turn(prompt: str) -> str:
    """One Pi (pi-mono) print-mode turn, driven directly."""
    proc = subprocess.run(["pi", "-p", prompt], capture_output=True)
    return proc.stdout.decode()
'''

VIA_URLOPEN = """
from urllib.request import urlopen

def poke_openclaw() -> None:
    urlopen("http://openclaw-gateway/health")
"""

BOUNDARY_EQUIVALENT = VIA_SUBPROCESS

NON_TRANSPORT_WITH_MARKER = '''
import asyncio
import os

async def orchestrate_openclaw_binding() -> None:
    """References the openclaw provider but performs no harness transport."""
    env = os.getenv("OPENCLAW_BINDING_ID", "")
    await asyncio.gather(asyncio.sleep(0))
    config = {"provider": "openclaw"}
    return config.get("provider"), env
'''


def _make_tree(tmp_path: Path, relative: str, source: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_openclaw_http_post_outside_boundary_is_a_violation(gate, tmp_path) -> None:
    _make_tree(tmp_path, "packages/maistro-core/src/maistro/products/caller.py", VIA_HTTPX)
    violations = gate.scan(tmp_path)
    assert {(v.call, v.line) for v in violations} == {
        ("httpx.AsyncClient", 6),
        (".post()", 7),
    }
    assert all("openclaw" in v.marker for v in violations)
    assert violations[0].render().endswith("outside the Provider boundary")


def test_local_client_http_verb_is_also_transport(gate, tmp_path) -> None:
    _make_tree(tmp_path, "packages/maistro-core/src/maistro/products/caller.py", VIA_LOCAL_CLIENT)
    assert [v.call for v in gate.scan(tmp_path)] == [".post()"]


def test_pi_subprocess_turn_outside_boundary_is_a_violation(gate, tmp_path) -> None:
    _make_tree(tmp_path, "packages/hive-conductor/backend/services/side_door.py", VIA_SUBPROCESS)
    violations = gate.scan(tmp_path)
    assert len(violations) == 1
    assert violations[0].call == "subprocess.run"


def test_direct_urlopen_call_is_transport(gate, tmp_path) -> None:
    _make_tree(tmp_path, "packages/maistro-rsi/src/maistro_rsi/poke.py", VIA_URLOPEN)
    violations = gate.scan(tmp_path)
    assert [v.call for v in violations] == ["urlopen"]


def test_provider_boundary_is_exempt(gate, tmp_path) -> None:
    _make_tree(
        tmp_path,
        "packages/maistro-core/src/maistro/capabilities/providers/pi.py",
        BOUNDARY_EQUIVALENT,
    )
    assert gate.scan(tmp_path) == []


def test_graph_side_harness_adapters_are_exempt(gate, tmp_path) -> None:
    _make_tree(
        tmp_path,
        "packages/maistro-core/src/maistro/graph/harness.py",
        VIA_SUBPROCESS,
    )
    assert gate.scan(tmp_path) == []


def test_marker_without_transport_is_not_a_violation(gate, tmp_path) -> None:
    _make_tree(
        tmp_path, "packages/maistro-core/src/maistro/products/config.py", NON_TRANSPORT_WITH_MARKER
    )
    assert gate.scan(tmp_path) == []


def test_transport_without_harness_marker_is_not_a_violation(gate, tmp_path) -> None:
    _make_tree(
        tmp_path,
        "packages/maistro-core/src/maistro/products/http.py",
        VIA_HTTPX.replace("OpenClaw gateway", "billing service").replace("openclaw", "billing"),
    )
    assert gate.scan(tmp_path) == []


def test_tests_and_gate_scripts_are_exempt(gate, tmp_path) -> None:
    _make_tree(tmp_path, "packages/maistro-core/tests/products/test_caller.py", VIA_HTTPX)
    _make_tree(tmp_path, "scripts/check-something.py", VIA_SUBPROCESS)
    assert gate.scan(tmp_path) == []


def test_main_exits_nonzero_and_prints_evidence(gate, tmp_path, capsys) -> None:
    _make_tree(tmp_path, "packages/maistro-core/src/maistro/products/caller.py", VIA_HTTPX)
    assert gate.main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "caller.py" in captured.err
    assert "#1613" in captured.err


def test_main_exits_zero_on_a_clean_tree(gate, tmp_path) -> None:
    _make_tree(tmp_path, "packages/maistro-core/src/maistro/products/fine.py", "x = 1\n")
    assert gate.main(["--root", str(tmp_path)]) == 0


def test_the_shipped_tree_is_clean(gate) -> None:
    """The real checkout must pass: existing harness transport is all inside
    the boundary, and hierarchy.py is the documented ADR-101 §2 peer client."""
    assert gate.scan(ROOT) == []
