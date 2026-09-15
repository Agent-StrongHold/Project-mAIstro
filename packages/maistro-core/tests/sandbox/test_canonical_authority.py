"""Canonical selector and host-path authority regression tests (#18)."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.sandbox import (
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    HostCapabilities,
    NoSuitableBackendError,
    SandboxConfig,
    build_selector,
)
from maistro.sandbox.paths import read_beneath, validate_host_root, write_beneath


def test_container_is_registered_only_when_host_evidence_names_a_launcher() -> None:
    capabilities = HostCapabilities(
        tiers=("container",),
        notes={},
        binaries={"container": "/usr/bin/docker"},
    )

    selector = build_selector(capabilities=capabilities)

    assert selector.available_tiers == ["container"]
    assert selector.select(TRUSTED_TOOL)[0] == "container"
    with pytest.raises(NoSuitableBackendError):
        selector.select(UNTRUSTED_CODE)


def test_injected_container_capability_without_launcher_stays_unsupported() -> None:
    selector = build_selector(capabilities=HostCapabilities(("container",), {}))

    assert selector.available_tiers == []


def test_network_compatibility_knob_is_rejected() -> None:
    with pytest.raises(ValueError, match="network is retired"):
        SandboxConfig(network=False)


def test_authorized_root_rejects_symlink_and_unapproved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import maistro.sandbox.paths as paths

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(paths, "AUTHORIZED_HOST_ROOTS", (allowed,))

    assert validate_host_root(allowed) == allowed
    with pytest.raises(ValueError, match="not authorized"):
        validate_host_root(tmp_path)

    outside = tmp_path / "outside"
    outside.mkdir()
    link = allowed / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        validate_host_root(link)


def test_host_file_transfer_does_not_follow_a_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"host secret")
    (root / "link").symlink_to(outside)

    with pytest.raises(OSError):
        read_beneath(root, "link")
    with pytest.raises(OSError):
        write_beneath(root, "link", b"overwrite")
    assert outside.read_bytes() == b"host secret"
