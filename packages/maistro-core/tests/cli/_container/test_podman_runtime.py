"""Tests for maistro.cli._container.podman_runtime — Podman socket discovery."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

from maistro.cli._container.podman_runtime import PodmanRuntime

# Captured at import: these tests assert DOCKER_HOST is *unchanged*, so they
# must compare against whatever the environment actually had, not against None.
_DOCKER_HOST_BEFORE = os.environ.get("DOCKER_HOST")


class TestFindSocket:
    def test_finds_xdg_runtime_dir_socket(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        monkeypatch.setattr(
            "maistro.cli._container.podman_runtime.os.path.exists",
            lambda p: p == "/run/user/1000/podman/podman.sock",
        )
        result = PodmanRuntime._find_socket()
        assert result == "/run/user/1000/podman/podman.sock"

    def test_falls_back_to_rootful_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        monkeypatch.setattr(
            "maistro.cli._container.podman_runtime.os.path.exists",
            lambda p: p == "/run/podman/podman.sock",
        )
        result = PodmanRuntime._find_socket()
        assert result == "/run/podman/podman.sock"

    def test_returns_none_when_no_socket_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        monkeypatch.setattr("maistro.cli._container.podman_runtime.os.path.exists", lambda p: False)
        result = PodmanRuntime._find_socket()
        assert result is None

    def test_uses_uid_fallback_when_xdg_runtime_dir_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setattr("maistro.cli._container.podman_runtime.os.getuid", lambda: 1234)
        monkeypatch.setattr(
            "maistro.cli._container.podman_runtime.os.path.exists",
            lambda p: p == "/run/user/1234/podman/podman.sock",
        )
        result = PodmanRuntime._find_socket()
        assert result == "/run/user/1234/podman/podman.sock"


class TestIsAvailable:
    def test_false_when_no_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runtime = PodmanRuntime()
        monkeypatch.setattr(PodmanRuntime, "_find_socket", staticmethod(lambda: None))
        assert runtime.is_available() is False

    def test_true_when_socket_found_and_ping_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = PodmanRuntime()
        monkeypatch.setattr(
            PodmanRuntime, "_find_socket", staticmethod(lambda: "/run/podman/podman.sock")
        )
        fake_client = MagicMock()
        runtime._client = fake_client
        result = runtime.is_available()
        assert result is True
        assert runtime._socket == "/run/podman/podman.sock"
        # An availability probe must not repoint every other Docker consumer in
        # the process. This used to assert the opposite — that `is_available()`
        # wrote DOCKER_HOST — which is how the leak survived: the test codified
        # it. Leaking it sent maistro.tools.sandbox.docker's `docker` CLI child
        # at Podman's socket, silently scoring sandboxed benchmarks as failures.
        assert os.environ.get("DOCKER_HOST") == _DOCKER_HOST_BEFORE

    def test_client_binds_to_socket_without_touching_environ(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = PodmanRuntime()
        monkeypatch.setattr(
            PodmanRuntime, "_find_socket", staticmethod(lambda: "/run/podman/podman.sock")
        )
        fake_docker = MagicMock()
        monkeypatch.setitem(sys.modules, "docker", fake_docker)

        assert runtime.client is fake_docker.DockerClient.return_value
        fake_docker.DockerClient.assert_called_once_with(base_url="unix:///run/podman/podman.sock")
        assert os.environ.get("DOCKER_HOST") == _DOCKER_HOST_BEFORE

    def test_false_when_super_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runtime = PodmanRuntime()
        monkeypatch.setattr(
            PodmanRuntime, "_find_socket", staticmethod(lambda: "/run/podman/podman.sock")
        )
        fake_client = MagicMock()
        fake_client.ping.side_effect = RuntimeError("boom")
        runtime._client = fake_client
        assert runtime.is_available() is False
