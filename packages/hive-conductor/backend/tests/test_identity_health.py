from __future__ import annotations

import sys


def _setup_config(*, modules: list[str], did: str | None, persisted: bool) -> dict:
    return {
        "optional_modules": modules,
        "user_did": did,
        "identity_persisted": persisted,
    }


def _identity_fixture() -> tuple[str, str]:
    from maistro.identity import ConductorSeed

    seed = ConductorSeed.generate()
    did = seed.did_key()
    mnemonic = " ".join(seed.mnemonic_words())
    seed.zero()
    return did, mnemonic


def _patch_identity_vault(monkeypatch, *, mnemonic: str | None = None, error=None) -> None:
    import maistro.vault as vault_module

    class FakeVault:
        def __init__(self, **kwargs) -> None:
            pass

        def use(self, name, callback):
            if error is not None:
                raise error
            assert mnemonic is not None
            return callback(mnemonic)

    monkeypatch.setattr(vault_module, "Vault", FakeVault)


def test_identity_health_reports_disabled_profile(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(modules=[], did=None, persisted=False),
    )

    assert identity_health() == {"status": "disabled", "reason": "crypto_identity_not_enabled"}


def test_identity_health_reports_operational_provisioned_identity(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    did, mnemonic = _identity_fixture()
    _patch_identity_vault(monkeypatch, mnemonic=mnemonic)
    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did=did, persisted=True
        ),
    )

    assert identity_health() == {"status": "operational", "reason": "provisioned"}


def test_identity_health_rejects_missing_encrypted_seed(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    from maistro.vault import SecretMissingError

    did, _ = _identity_fixture()
    _patch_identity_vault(monkeypatch, error=SecretMissingError("missing"))
    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did=did, persisted=True
        ),
    )

    assert identity_health() == {"status": "misconfigured", "reason": "identity_seed_missing"}


def test_identity_health_rejects_malformed_encrypted_seed(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    did, _ = _identity_fixture()
    _patch_identity_vault(monkeypatch, mnemonic="not a valid BIP39 mnemonic")
    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did=did, persisted=True
        ),
    )

    assert identity_health() == {"status": "misconfigured", "reason": "identity_seed_invalid"}


def test_identity_health_rejects_seed_for_different_persisted_did(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    persisted_did, _ = _identity_fixture()
    other_did, other_mnemonic = _identity_fixture()
    assert persisted_did != other_did
    _patch_identity_vault(monkeypatch, mnemonic=other_mnemonic)
    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did=persisted_did, persisted=True
        ),
    )

    assert identity_health() == {
        "status": "misconfigured",
        "reason": "identity_seed_did_mismatch",
    }


def test_identity_health_reports_unavailable_vault(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    from maistro.vault import VaultUnavailableError

    did, _ = _identity_fixture()
    _patch_identity_vault(monkeypatch, error=VaultUnavailableError("cannot decrypt"))
    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did=did, persisted=True
        ),
    )

    assert identity_health() == {
        "status": "misconfigured",
        "reason": "identity_vault_unavailable",
    }


def test_identity_health_distinguishes_missing_runtime(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    monkeypatch.setitem(sys.modules, "maistro.identity", None)
    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did="did:key:znot-used", persisted=True
        ),
    )

    assert identity_health() == {"status": "unavailable", "reason": "identity_runtime_missing"}


def test_identity_health_reports_selected_but_unprovisioned(monkeypatch) -> None:
    import stores
    from services.identity_health import identity_health

    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did=None, persisted=False
        ),
    )

    assert identity_health() == {"status": "misconfigured", "reason": "identity_not_provisioned"}
