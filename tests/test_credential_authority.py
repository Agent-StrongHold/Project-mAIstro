"""The credential authority has one owner per responsibility (#1186)."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "credential-authority.json"
CHECKER = ROOT / "scripts" / "check-credential-authority.py"

_spec = importlib.util.spec_from_file_location("credential_authority_checker", CHECKER)
assert _spec is not None and _spec.loader is not None
_checker = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _checker
_spec.loader.exec_module(_checker)


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_credential_authority_ledger_records_live_and_retired_surfaces() -> None:
    ledger = _ledger()
    canonical = ledger["canonical"]
    retired = ledger["retired"]

    assert Path(ROOT / canonical["product_crud"]).is_file()
    store_path, store_class = canonical["encrypted_store"].split("::", 1)
    assert store_class == "UserCredentialStore"
    assert Path(ROOT / store_path).is_file()
    assert canonical["runtime_selection"].startswith(
        "packages/maistro-core/src/maistro/credentials/router.py::"
    )
    assert retired == [
        {
            "path": "packages/hive-conductor/backend/services/credential_store_v2.py",
            "disposition": "RETIRE",
            "replacement": "services.user_credentials -> maistro.credentials.store.UserCredentialStore",
            "reason": "The v2 PostgREST service exposed id-only reads, secret reads, updates, and deletes without a principal predicate. It had no production callers and is deleted rather than made into a second credential authority.",
            "issue": "#1186",
        }
    ]
    assert not (ROOT / retired[0]["path"]).exists()


def test_reachable_credential_surfaces_are_classified_and_scoped() -> None:
    """The authority ledger must be joined to the production import graph."""
    assert _checker.audit() == []


def test_canonical_store_isolation_has_uniform_missing_record_behavior() -> None:
    """The replacement store scopes every record operation by principal.

    Retirement removes the unsafe id-only API rather than preserving it under a
    new name. Keep the canonical replacement's two-user contract explicit: an
    owner-id guess cannot read or delete another user's record, and the missing
    result is indistinguishable from an actually absent provider.
    """
    from cryptography.fernet import Fernet

    from maistro.credentials.store import CredentialNotFound, UserCredentialStore

    with tempfile.TemporaryDirectory() as directory:
        store = UserCredentialStore(Path(directory), master_key=Fernet.generate_key())
        store.set_secret("alice", "jira", "alice-secret")

        assert store.list_providers_for_user("bob") == {}
        assert not store.has_secret("bob", "jira")
        assert store.delete_secret("bob", "jira") is False
        assert store.has_secret("alice", "jira")

        with pytest.raises(CredentialNotFound) as guessed:
            store.use_secret("bob", "jira", lambda secret: secret)
        with pytest.raises(CredentialNotFound) as absent:
            store.use_secret("carol", "jira", lambda secret: secret)
        assert str(guessed.value) == str(absent.value)
        assert store.use_secret("alice", "jira", lambda secret: secret) == "alice-secret"

        # Guessing the same provider on a write rotates only Bob's own bucket.
        store.set_secret("bob", "jira", "bob-secret")
        assert store.use_secret("alice", "jira", lambda secret: secret) == "alice-secret"
        assert store.delete_secret("bob", "jira") is True
        assert store.delete_secret("bob", "jira") is False
        assert store.delete_secret("carol", "jira") is False
        assert store.list_providers_for_user("bob") == store.list_providers_for_user("carol")
        ciphertext = (Path(directory) / "user_credentials.enc").read_bytes()
        assert b"alice-secret" not in ciphertext
        assert b"bob-secret" not in ciphertext


def test_retired_module_cannot_be_imported_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retirement ledger also blocks stale production imports."""
    with tempfile.TemporaryDirectory() as directory:
        package_root = Path(directory) / "packages" / "demo" / "src"
        package_fixture = package_root / "demo" / "adapter.py"
        package_fixture.parent.mkdir(parents=True)
        package_fixture.write_text(
            "from services.credential_store_v2 import CredentialV2\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(_checker, "ROOT", Path(directory))
        failures = _checker.audit(
            {
                "reachable": [],
                "retired": [{"path": "packages/demo/credential_store_v2.py"}],
            },
            modules={"demo.adapter": package_fixture},
            reachable=set(),
        )
        assert any("imports retired credential module" in failure for failure in failures)


def test_renamed_reachable_style_store_is_detected_by_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store cannot evade review by dropping ``credential_store`` from its name."""
    source = """
import httpx
from cryptography.fernet import Fernet

class Repository:
    def __init__(self):
        self._fernet = Fernet.generate_key()

    def get(self, record_id):
        return httpx.get('/records', params={'id': record_id})

    def rotate(self, record_id, secret):
        return self._fernet.encrypt(secret.encode())

    def delete(self, record_id):
        return httpx.delete('/records', params={'id': record_id})
"""
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "repository.py"
        fixture.write_text(source, encoding="utf-8")
        assert _checker.is_credential_surface(fixture)

        # Feed the renamed implementation through the ledger join as a
        # reachable module. Detection alone is not enough: the gate must reject
        # a reachable surface that has no authority classification.
        package_root = Path(directory) / "packages" / "demo" / "src"
        package_fixture = package_root / "demo" / "repository.py"
        package_fixture.parent.mkdir(parents=True)
        package_fixture.write_text(source, encoding="utf-8")
        monkeypatch.setattr(_checker, "ROOT", Path(directory))
        failures = _checker.audit(
            {"reachable": [], "retired": [{"path": "deleted.py"}]},
            modules={"demo.repository": package_fixture},
            reachable={"demo.repository"},
        )
        assert any("not classified" in failure for failure in failures)


_UNSCOPED_STORE_SOURCE = """
import httpx
from cryptography.fernet import Fernet

class SecretRepository:
    def __init__(self):
        self._fernet = Fernet.generate_key()

    def get(self, record_id):
        return httpx.get('/records', params={'id': record_id})

    def rotate(self, record_id, secret):
        return self._fernet.encrypt(secret.encode())

    def delete(self, record_id):
        return httpx.delete('/records', params={'id': record_id})
"""


def _scope_ledger_entry(kind: str) -> dict:
    return {
        "path": "packages/demo/src/demo/secrets.py",
        "kind": kind,
        "authority": "canonical per-user credential authority",
        "scope": "authenticated request principal user id",
        "storage": "Fernet-encrypted records",
    }


@pytest.mark.parametrize("kind", ["product_crud", "encrypted_store", "protocol_adapter"])
@pytest.mark.parametrize(
    "source",
    [
        _UNSCOPED_STORE_SOURCE,
        # The prior checker accepted these decorative scope tokens.
        _UNSCOPED_STORE_SOURCE.replace(
            "return httpx.", "user = 'decorative'\n        return httpx."
        ).replace("return self._fernet", "owner = 'decorative'\n        return self._fernet"),
        _UNSCOPED_STORE_SOURCE.replace("self, record_id", "self, user_id, record_id"),
        _UNSCOPED_STORE_SOURCE + "\n    def list(self):\n        return httpx.get('/records')\n",
        # A list-only addition must not gain authority by classification either.
        "class SecretRepository:\n    def list(self):\n        return self.secrets\n",
    ],
    ids=["id-only", "decorative-local", "unused-owner", "unscoped-list", "list-only"],
)
def test_classification_cannot_authorize_another_credential_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, source: str
) -> None:
    """Both reported counterexamples fail even with plausible ledger claims.

    Start with the complete approved census: the only violation must be the
    candidate's extra implementation, not a missing canonical fixture.
    """
    trusted = _ledger()
    modules = {}
    for index, entry in enumerate(trusted["reachable"]):
        path = tmp_path / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((ROOT / entry["path"]).read_text(), encoding="utf-8")
        modules[str(index)] = path
    entry = _scope_ledger_entry(kind)
    fixture = tmp_path / entry["path"]
    fixture.parent.mkdir(parents=True)
    fixture.write_text(source, encoding="utf-8")
    modules["demo.secrets"] = fixture
    monkeypatch.setattr(_checker, "ROOT", tmp_path)
    candidate = copy.deepcopy(trusted)
    candidate["reachable"].append(entry)

    # Exercise both an established trusted policy and first-landing bootstrap.
    for policy in (trusted, None):
        failures = _checker.audit(
            candidate, modules=modules, reachable=set(modules), trusted=policy
        )
        assert any(
            "census" in failure or "differs from trusted base" in failure for failure in failures
        ), failures
        if kind != "protocol_adapter":
            assert any("scope at a canonical storage sink" in failure for failure in failures)


@pytest.mark.parametrize(
    "operation",
    [
        "def get(self, record_id):\n        user = 'decoration'\n        return self.secrets[record_id]",
        "def rotate(self, user_id, record_id, secret):\n        self.secrets[record_id] = secret",
        "def delete(self, user_id, record_id):\n        del self.secrets[record_id]",
        "def list(self):\n        return self.secrets",
    ],
    ids=["read", "rotate", "delete", "list"],
)
def test_unscoped_operations_inside_an_approved_module_fail(tmp_path: Path, operation: str) -> None:
    path = tmp_path / "store.py"
    path.write_text("class SecretStore:\n    " + operation + "\n", encoding="utf-8")
    failures = _checker._owner_scope_failures(
        "packages/maistro-core/src/maistro/credentials/store.py", path
    )
    assert len(failures) == 1
    assert "scope at a canonical storage sink" in failures[0]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


@pytest.mark.parametrize("base_has_ledger", [False, True])
def test_candidate_policy_cannot_become_its_own_trusted_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_has_ledger: bool
) -> None:
    """Use real git history, including a candidate-committed policy edit."""
    policy = _ledger()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ratchet_provenance.py").write_text(
        (ROOT / "scripts" / "ratchet_provenance.py").read_text(), encoding="utf-8"
    )
    ledger_path = tmp_path / "quality" / "credential-authority.json"
    ledger_path.parent.mkdir()
    if base_has_ledger:
        ledger_path.write_text(json.dumps(policy), encoding="utf-8")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Credential authority test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "independent base")
    base = _git(tmp_path, "rev-parse", "HEAD")

    candidate = copy.deepcopy(policy)
    candidate["reachable"].append(_scope_ledger_entry("encrypted_store"))
    candidate["retired"] = []
    ledger_path.write_text(json.dumps(candidate), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "candidate attempts to self-approve")
    monkeypatch.setenv("RATCHET_BASE_REV", base)
    monkeypatch.setattr(_checker, "ROOT", tmp_path)
    monkeypatch.setattr(_checker, "LEDGER", ledger_path)

    trusted = _checker._trusted_ledger()
    assert trusted == (policy if base_has_ledger else None)
    assert _checker._policy_failures(candidate, trusted)
    assert _checker._policy_failures(policy, trusted) == []
    # The production audit must actually invoke the resolver, not merely expose it.
    assert any("credential" in failure for failure in _checker.audit(modules={}, reachable=set()))


def test_unresolvable_authority_baseline_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable():
        raise RuntimeError("trusted baseline could not be read")

    monkeypatch.setattr(_checker, "_trusted_ledger", unavailable)
    assert _checker.main() == 1


def test_trusted_policy_prevents_reclassification_and_retirement_erasure() -> None:
    trusted = _ledger()
    candidate = copy.deepcopy(trusted)
    candidate["reachable"][0]["kind"] = "deployment_secret_vault"
    candidate["canonical"]["encrypted_store"] = "another.Store"
    candidate["retired"] = []
    failures = _checker._policy_failures(candidate, trusted)
    assert len(failures) == 3
    assert all("differs from trusted base" in failure for failure in failures)
