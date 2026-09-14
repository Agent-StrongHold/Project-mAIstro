"""Conformance for the shipped Tier-1 Kata backend and canonical wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.sandbox import (
    BENCHMARK_EVAL,
    BROWSER_AUTOMATION,
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    HostCapabilities,
    SandboxConfig,
    build_selector,
)
from maistro.sandbox.backends.kata import KataSandboxBackend
from maistro.sandbox.network import EgressGrant, EgressMode


def _backend() -> KataSandboxBackend:
    return KataSandboxBackend(
        docker="/usr/bin/docker",
        kata_runtime="/usr/bin/kata-runtime",
        image="example/sandbox:locked",
    )


def test_kata_launch_has_vm_runtime_and_no_host_socket(tmp_path: Path) -> None:
    argv = _backend().build_run_argv(
        SandboxConfig(workspace_host=str(tmp_path)), "kata-test", tmp_path
    )

    assert "--runtime=kata" in argv
    assert "--network=none" in argv
    assert "/var/run/docker.sock" not in argv
    assert "--cap-drop=ALL" in argv
    assert f"{tmp_path}:/workspace:rw" in argv


def test_kata_host_network_requires_explicit_reason() -> None:
    config = SandboxConfig(
        egress=EgressGrant(mode=EgressMode.HOST, reason="approved first-party API")
    )
    argv = _backend().build_run_argv(config, "kata-test", Path("/tmp/work"))
    assert "--network=host" in argv
    assert "--network=none" not in argv


def test_kata_rejects_scoped_egress_instead_of_granting_host_network() -> None:
    config = SandboxConfig(
        egress=EgressGrant(
            mode=EgressMode.SCOPED,
            allow=("api.example.com",),
            reason="one API",
        )
    )
    with pytest.raises(ValueError, match="cannot filter"):
        _backend().build_run_argv(config, "kata-test", Path("/tmp/work"))


def test_vm_capability_selects_every_standard_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import maistro.sandbox.backends.kata as kata_module

    monkeypatch.setattr(kata_module, "KataSandboxBackend", _backend)
    selector = build_selector(capabilities=HostCapabilities(tiers=("vm",), notes={}))

    for policy in (UNTRUSTED_CODE, BENCHMARK_EVAL, TRUSTED_TOOL, BROWSER_AUTOMATION):
        tier, _backend_instance = selector.select(policy)
        assert tier == "vm"


def test_kata_backend_claims_only_the_protocol_vm_tier() -> None:
    assert _backend().tier == "vm"
    assert isinstance(_backend(), KataSandboxBackend)
