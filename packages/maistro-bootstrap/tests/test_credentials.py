"""Tests for bootstrap-credentials staging (SPEC-072726-3439 Phase 1)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from maistro_bootstrap.credentials import (
    BOOTSTRAP_CREDENTIALS_FILENAME,
    build_bootstrap_credentials,
    validate_bootstrap_credentials,
    write_bootstrap_credentials,
)
from maistro_bootstrap.schema import InstallAnswersV1


def _answers(**overrides: object) -> InstallAnswersV1:
    return InstallAnswersV1.model_validate(
        {"admin_user": "root-admin", "daily_driver_user": "alice", **overrides}
    )


def test_build_payload_carries_names_and_crypto_module() -> None:
    creds = build_bootstrap_credentials(_answers(), admin_password="pw-a", user_password="pw-u")
    assert creds["admin_username"] == "root-admin"
    assert creds["user_username"] == "alice"
    assert creds["optional_modules"] == ["crypto_identity"]
    assert creds["hardware_preset"] == "auto"


def test_no_crypto_profile_omits_identity_module() -> None:
    creds = build_bootstrap_credentials(
        _answers(crypto_profile="no_crypto"), admin_password="a", user_password="u"
    )
    assert creds["optional_modules"] == []


def test_write_is_owner_only_and_round_trips(tmp_path: Path) -> None:
    creds = build_bootstrap_credentials(_answers(), admin_password="a", user_password="u")
    path = write_bootstrap_credentials(tmp_path, creds)
    assert path.name == BOOTSTRAP_CREDENTIALS_FILENAME
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == creds


def test_validate_rejects_missing_and_empty_secrets() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        validate_bootstrap_credentials({"admin_username": "a"})
    with pytest.raises(ValueError, match="non-empty"):
        validate_bootstrap_credentials(
            {
                "admin_username": "a",
                "admin_password": "",
                "user_username": "u",
                "user_password": "x",
            }
        )


def test_answers_schema_still_rejects_password_fields() -> None:
    """AC-6: the answers schema must never grow secret fields silently."""
    answers = InstallAnswersV1.model_validate({"admin_password": "oops", "user_password": "oops"})
    dumped = answers.model_dump(mode="json")
    assert "admin_password" not in dumped
    assert "user_password" not in dumped
