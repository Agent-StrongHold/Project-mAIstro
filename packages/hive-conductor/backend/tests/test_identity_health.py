from __future__ import annotations

import sys


def _setup_config(*, modules: list[str], did: str | None, persisted: bool) -> dict:
    return {
        "optional_modules": modules,
        "user_did": did,
        "identity_persisted": persisted,
    }


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

    from maistro.identity import ConductorSeed

    seed = ConductorSeed.generate()
    did = seed.did_key()
    seed.zero()
    monkeypatch.setattr(
        stores.sessions,
        "get",
        lambda key, default=None: _setup_config(
            modules=["crypto_identity"], did=did, persisted=True
        ),
    )

    assert identity_health() == {"status": "operational", "reason": "provisioned"}


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
