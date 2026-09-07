"""The credential boundary between host environments and candidate exec (#78).

Unattended candidates receive no ambient host credentials. These tests pin the
boundary as a *property of construction* — the ambient environment is never
read on POSIX — rather than a filter that happens to catch today's secret
shapes. A filter can be missed by a new secret format; a dict that is never
consulted cannot leak.
"""

from __future__ import annotations

import os

import pytest

from maistro.credentials.types import CredentialRecord
from maistro.sandbox.credential_boundary import (
    CANDIDATE_BASE_ENV,
    candidate_env,
    grant_from_credential,
    redact_env,
)


class TestCandidateEnv:
    def test_default_is_exactly_the_base(self) -> None:
        assert candidate_env() == dict(CANDIDATE_BASE_ENV)

    def test_base_carries_no_identity_or_secret_shaped_names(self) -> None:
        # HOME/USER point the candidate at the operator's config files; every
        # name here is one the ambient environment uses to carry credentials.
        forbidden = {
            "HOME",
            "USER",
            "LOGNAME",
            "AWS_SECRET_ACCESS_KEY",
            "OPENAI_API_KEY",
            "GITHUB_TOKEN",
            "LITELLM_MASTER_KEY",
            "DATABASE_URL",
        }
        assert forbidden.isdisjoint(CANDIDATE_BASE_ENV)

    def test_ambient_secrets_are_not_inherited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The harness process's own credentials never reach the candidate.

        LITELLM_MASTER_KEY is the live case: maistro_rsi.gateway reads it from
        the environment of the RSI process, and the pre-boundary LocalSandbox
        handed it to every candidate ``bash -c`` via plain inheritance.
        """
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 36)
        env = candidate_env()
        assert "LITELLM_MASTER_KEY" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "GITHUB_TOKEN" not in env

    def test_ambient_path_is_not_inherited_on_posix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PATH is a literal, never the host's: an ambient PATH pointing at a
        bin directory stuffed with credential helpers is an indirect channel."""
        monkeypatch.setattr(os, "name", "posix", raising=False)
        monkeypatch.setenv("PATH", "/home/operator/secret-helpers:/usr/bin")
        assert candidate_env()["PATH"] == CANDIDATE_BASE_ENV["PATH"]

    def test_explicit_grants_pass_through(self) -> None:
        env = candidate_env({"MY_TOOL_TOKEN": "scope:limited"})
        assert env["MY_TOOL_TOKEN"] == "scope:limited"

    def test_grants_cannot_shadow_base_names(self) -> None:
        with pytest.raises(ValueError, match="shadows the sandbox base"):
            candidate_env({"PATH": "/home/operator/secret-helpers"})
        with pytest.raises(ValueError, match="shadows the sandbox base"):
            candidate_env({"LANG": "en_US.UTF-8"})

    def test_no_grants_leaves_base_untouched(self) -> None:
        assert candidate_env(None) == dict(CANDIDATE_BASE_ENV)
        assert candidate_env({}) == dict(CANDIDATE_BASE_ENV)


class TestWindowsForwarding:
    def test_windows_forwards_system_basics_by_name_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "name", "nt", raising=False)
        monkeypatch.setenv("SYSTEMROOT", r"C:\\Windows")
        monkeypatch.setenv("SECRET_HARNESS_KEY", "sk-should-not-forward")
        env = candidate_env()
        # python.exe cannot start without SYSTEMROOT; forwarding it by name
        # keeps Windows children usable without spreading the environment.
        assert env["SYSTEMROOT"] == r"C:\\Windows"
        assert "SECRET_HARNESS_KEY" not in env

    def test_windows_forwarded_path_is_the_real_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Windows a POSIX PATH literal is meaningless (executable lookup
        needs the real PATH), so the forwarded value wins over the base."""
        monkeypatch.setattr(os, "name", "nt", raising=False)
        monkeypatch.setenv("PATH", r"C:\\Windows\\System32")
        assert candidate_env()["PATH"] == r"C:\\Windows\\System32"


class TestProviderMediatedGrants:
    def test_grant_comes_from_a_router_record(self) -> None:
        record = CredentialRecord(key_id="k1", provider="openai", api_key="sk-pool-key")
        assert grant_from_credential(record, "OPENAI_API_KEY") == {"OPENAI_API_KEY": "sk-pool-key"}

    def test_grant_refuses_reserved_names(self) -> None:
        record = CredentialRecord(key_id="k1", provider="openai", api_key="sk-pool-key")
        with pytest.raises(ValueError, match="shadows the sandbox base"):
            grant_from_credential(record, "PATH")

    def test_grant_type_gates_provenance(self) -> None:
        """A bare string key has no scope, no cooldown and no Binding that
        authorized it; it does not get to pretend it came from the pool."""
        with pytest.raises(TypeError):
            grant_from_credential("sk-ambient-string", "OPENAI_API_KEY")  # type: ignore[arg-type]


class TestRedaction:
    def test_redact_env_masks_values_and_keeps_names(self) -> None:
        redacted = redact_env({"OPENAI_API_KEY": "sk-pool-key", "PATH": "/bin"})
        assert redacted == {"OPENAI_API_KEY": "***", "PATH": "***"}

    def test_redacted_values_reveal_nothing_of_the_secret(self) -> None:
        # Not a prefix, not a digest — masking entirely is the only form that
        # cannot be brute-forced back from a truncated or hashed key.
        assert "***" not in {"sk-pool-key"}
        assert redact_env({"K": "sk-pool-key"})["K"] != "sk-pool-key"
