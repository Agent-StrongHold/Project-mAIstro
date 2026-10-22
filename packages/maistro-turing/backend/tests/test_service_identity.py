"""The governed service identity: issuance, bounding, and readiness (#858).

Every test drives the production activation path — ``config.build_registry()``
over the real environment surface, or the composed application — plus a source
ratchet proving the retired default credential cannot reappear anywhere in the
package that activates Turing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: The retired built-in credential from the pre-#858 config, assembled so this
#: ratchet file does not itself contain the literal it forbids.
HISTORICAL_DEFAULT_KEY = "sk-svc-turing-dev-" + "internal"


def test_no_builtin_credential_exists_in_the_activation_package() -> None:
    """A committed/default known key must not exist on the activation path."""
    sources = list(BACKEND_ROOT.rglob("*.py"))
    sources.append(BACKEND_ROOT.parent / "README.md")
    offenders = [
        str(path) for path in sources if HISTORICAL_DEFAULT_KEY in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_registry_authenticates_only_the_configured_key() -> None:
    from ..config import build_registry

    registry = build_registry()
    configured = os.environ["TURING_SERVICE_KEY"]
    assert registry.authenticate(configured) is not None
    # The retired default (and any other key) authenticates nobody.
    assert registry.authenticate(HISTORICAL_DEFAULT_KEY) is None
    assert registry.authenticate("sk-svc-turing-anything-else") is None


def test_identity_maps_into_the_canonical_scope_model_and_nothing_wider() -> None:
    from maistro.auth import Scope

    from ..config import TURING_SERVICE_NAME, build_registry
    from ..middleware.auth import TURING_INTERNAL_SCOPES

    identity = build_registry().services[TURING_SERVICE_NAME]
    assert identity.name == TURING_SERVICE_NAME
    assert identity.scopes == TURING_INTERNAL_SCOPES
    assert identity.scopes <= {
        Scope.TURING_CHAT,
        Scope.TURING_VAULT_READ,
        Scope.TURING_VAULT_WRITE,
    }
    assert not identity.has_scope(Scope.ADMIN)
    assert not identity.has_scope(Scope.DASHBOARD)


def test_startup_refuses_to_mint_an_identity_wider_than_the_internal_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config drift (or a wider canonical category) must fail startup."""
    from maistro.auth import Scope

    from .. import config
    from ..middleware.auth import TURING_INTERNAL_SCOPES

    widened = frozenset(TURING_INTERNAL_SCOPES | {Scope.ADMIN})
    monkeypatch.setattr(config, "canonical_turing_scopes", lambda: widened)
    config.build_registry.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="allowlist"):
            config.build_registry()
    finally:
        config.build_registry.cache_clear()


def test_service_key_must_be_explicit_even_when_empty_or_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ..config import turing_service_key

    monkeypatch.delenv("TURING_SERVICE_KEY", raising=False)
    monkeypatch.delenv("TURING_SERVICE_KEY_FILE", raising=False)
    with pytest.raises(RuntimeError, match="TURING_SERVICE_KEY must be set"):
        turing_service_key()
    monkeypatch.setenv("TURING_SERVICE_KEY", "   ")
    with pytest.raises(RuntimeError, match="TURING_SERVICE_KEY must be set"):
        turing_service_key()


def test_rotation_through_a_secret_file_without_source_or_image_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from .. import config

    monkeypatch.delenv("TURING_SERVICE_KEY", raising=False)
    key_file = tmp_path / "turing-service-key"
    key_file.write_text("rotated-turing-key-1\n", encoding="utf-8")
    monkeypatch.setenv("TURING_SERVICE_KEY_FILE", str(key_file))
    config.build_registry.cache_clear()
    try:
        registry = config.build_registry()
        assert registry.authenticate("rotated-turing-key-1") is not None
        assert registry.authenticate("test-turing-service-key") is None

        # Rotate: replace the mounted secret's contents and reload; the old
        # key is revoked without touching a single source or image byte.
        key_file.write_text("rotated-turing-key-2\n", encoding="utf-8")
        config.build_registry.cache_clear()
        registry = config.build_registry()
        assert registry.authenticate("rotated-turing-key-2") is not None
        assert registry.authenticate("rotated-turing-key-1") is None
    finally:
        config.build_registry.cache_clear()


def test_env_key_takes_precedence_over_a_stale_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from ..config import turing_service_key

    key_file = tmp_path / "stale"
    key_file.write_text("stale-key\n", encoding="utf-8")
    monkeypatch.setenv("TURING_SERVICE_KEY", "fresh-key")
    monkeypatch.setenv("TURING_SERVICE_KEY_FILE", str(key_file))
    assert turing_service_key() == "fresh-key"


def test_missing_or_empty_secret_file_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from ..config import turing_service_key

    monkeypatch.delenv("TURING_SERVICE_KEY", raising=False)
    monkeypatch.setenv("TURING_SERVICE_KEY_FILE", str(tmp_path / "absent"))
    with pytest.raises(RuntimeError, match="cannot be read"):
        turing_service_key()
    empty = tmp_path / "empty"
    empty.write_text("\n \n", encoding="utf-8")
    monkeypatch.setenv("TURING_SERVICE_KEY_FILE", str(empty))
    with pytest.raises(RuntimeError, match="contains no key"):
        turing_service_key()


def test_service_identity_status_reports_unavailable_without_a_governed_identity() -> None:
    from maistro.auth import ServiceKeyRegistry

    from ..config import TURING_SERVICE_NAME, service_identity_status

    assert service_identity_status(None) == (
        False,
        "turing service identity not configured",
    )
    assert service_identity_status(ServiceKeyRegistry())[0] is False

    drifted = ServiceKeyRegistry()
    drifted.load_dict({TURING_SERVICE_NAME: {"key": "k", "scopes": ["llm:*"]}})
    configured, reason = service_identity_status(drifted)
    assert configured is False
    assert "allowlist" in reason
