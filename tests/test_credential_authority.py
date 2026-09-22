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


def test_ledger_must_be_an_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger_file = tmp_path / "credential-authority.json"
    ledger_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(_checker, "LEDGER", ledger_file)
    with pytest.raises(ValueError, match="must be an object"):
        _checker._ledger()


def test_trusted_ledger_must_be_an_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A trusted baseline that parses to a non-object fails closed."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ratchet_provenance.py").write_text(
        (ROOT / "scripts" / "ratchet_provenance.py").read_text(), encoding="utf-8"
    )
    ledger_path = tmp_path / "quality" / "credential-authority.json"
    ledger_path.parent.mkdir()
    ledger_path.write_text("[]", encoding="utf-8")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Credential authority test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base carries a malformed ledger")
    base = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "candidate.txt").write_text("candidate work\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "candidate change")
    monkeypatch.setenv("RATCHET_BASE_REV", base)
    monkeypatch.setattr(_checker, "ROOT", tmp_path)
    monkeypatch.setattr(_checker, "LEDGER", ledger_path)
    with pytest.raises(ValueError, match="trusted credential authority ledger"):
        _checker._trusted_ledger()


def test_scope_lint_rejects_unowned_secondary_data_access(tmp_path: Path) -> None:
    """Results of ``self._load`` are only sinks through owned record access."""
    path = tmp_path / "store.py"
    path.write_text(
        "class SecretStore:\n"
        "    def get(self, user_id, record_id):\n"
        "        data = self._load(user_id)\n"
        "        return data.keys()\n",
        encoding="utf-8",
    )
    failures = _checker._owner_scope_failures("packages/demo/store.py", path)
    assert failures == [
        "packages/demo/store.py: get lacks owner/principal scope at a canonical storage sink"
    ]


def test_scope_lint_rejects_unowned_config_reads(tmp_path: Path) -> None:
    path = tmp_path / "store.py"
    path.write_text(
        "class SecretStore:\n"
        "    def get(self, user_id, record_id):\n"
        "        return _read_config(record_id)\n",
        encoding="utf-8",
    )
    failures = _checker._owner_scope_failures("packages/demo/store.py", path)
    assert failures == [
        "packages/demo/store.py: get lacks owner/principal scope at a canonical storage sink"
    ]


def test_owner_scope_lint_fails_closed_on_unreadable_surface(tmp_path: Path) -> None:
    failures = _checker._owner_scope_failures("packages/demo/store.py", tmp_path / "missing.py")
    assert failures == ["packages/demo/store.py: cannot parse owner-scoped credential surface"]


def test_surface_detection_fails_closed_on_unreadable_file(tmp_path: Path) -> None:
    assert _checker.is_credential_surface(tmp_path / "missing.py") is False


def test_retired_import_scan_fails_closed_on_unreadable_file(tmp_path: Path) -> None:
    assert _checker._imports_module_stem(tmp_path / "missing.py", "credential_store_v2") is False


def test_surface_entries_ignores_non_list_reachable() -> None:
    assert _checker._surface_entries({"reachable": 42}) == []


_SECRET_REPOSITORY_SOURCE = """
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


def _demo_ledger_entry(**overrides: object) -> dict:
    entry: dict = {
        "path": "packages/demo/src/demo/secrets.py",
        "kind": "protocol_adapter",
        "authority": "canonical adapter delegating to the canonical authority",
        "scope": "authorized binding scope",
        "storage": "no credential storage of its own",
    }
    entry.update(overrides)
    return entry


def _demo_root(
    tmp_path: Path, *, source: str = "# not a credential surface\n"
) -> tuple[Path, Path]:
    """A fake repository root whose one package module exists on disk."""
    fixture = tmp_path / "packages" / "demo" / "src" / "demo" / "secrets.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(source, encoding="utf-8")
    return fixture, fixture


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("duplicate_paths", "duplicate or missing paths"),
        ("outside_module_graph", "outside the reachability module graph"),
        ("unreachable", "classified credential surface is unreachable"),
        ("unsupported_kind", "unsupported credential surface kind"),
        ("empty_scope", "must declare scope"),
        ("empty_authority", "must name its authority"),
        ("authority_without_canonical", "authority must name canonical"),
        ("scope_without_contract_terms", "scope does not satisfy the runtime_selection contract"),
    ],
)
def test_audit_reports_each_ledger_entry_defect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
    message: str,
) -> None:
    """Every entry-validation branch names its own defect, not a pooled one."""
    fixture, _ = _demo_root(tmp_path)
    entry = _demo_ledger_entry()
    modules = {"demo.secrets": fixture}
    reachable = {"demo.secrets"}
    if defect == "duplicate_paths":
        reachable_entries = [entry, _demo_ledger_entry()]
    elif defect == "outside_module_graph":
        modules, reachable = {}, set()
        reachable_entries = [entry]
    elif defect == "unreachable":
        reachable = set()
        reachable_entries = [entry]
    elif defect == "unsupported_kind":
        reachable_entries = [_demo_ledger_entry(kind="mystery_store")]
    elif defect == "empty_scope":
        reachable_entries = [_demo_ledger_entry(scope="   ")]
    elif defect == "empty_authority":
        reachable_entries = [_demo_ledger_entry(authority="   ")]
    elif defect == "authority_without_canonical":
        reachable_entries = [_demo_ledger_entry(authority="an unrelated authority")]
    else:
        reachable_entries = [
            _demo_ledger_entry(
                kind="runtime_selection",
                authority="canonical runtime selection authority",
                scope="no contract term here",
            )
        ]

    monkeypatch.setattr(_checker, "ROOT", tmp_path)
    failures = _checker.audit(
        {"reachable": reachable_entries, "retired": [{"path": "packages/demo/retired.py"}]},
        modules=modules,
        reachable=reachable,
        trusted=_ledger(),
    )
    assert any(message in failure for failure in failures), failures


def test_protocol_adapter_cannot_become_its_own_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, _ = _demo_root(tmp_path, source=_SECRET_REPOSITORY_SOURCE)
    monkeypatch.setattr(_checker, "ROOT", tmp_path)
    failures = _checker.audit(
        {
            "reachable": [_demo_ledger_entry(authority="an independent storage authority")],
            "retired": [{"path": "packages/demo/retired.py"}],
        },
        modules={"demo.secrets": fixture},
        reachable={"demo.secrets"},
        trusted=_ledger(),
    )
    assert any("does not name canonical authority" in failure for failure in failures), failures


@pytest.mark.parametrize(
    ("retired", "message"),
    [
        (["not-a-record"], "retired record is not an object"),
        ([{"path": "packages/demo/existing.py"}], "retired credential implementation still exists"),
        ([], "must record at least one retired decision"),
    ],
)
def test_audit_reports_retirement_defects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retired: list,
    message: str,
) -> None:
    fixture, _ = _demo_root(tmp_path)
    (tmp_path / "packages" / "demo" / "existing.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(_checker, "ROOT", tmp_path)
    failures = _checker.audit(
        {"reachable": [_demo_ledger_entry()], "retired": retired},
        modules={"demo.secrets": fixture},
        reachable={"demo.secrets"},
        trusted=_ledger(),
    )
    assert any(message in failure for failure in failures), failures


def test_retired_path_detected_as_a_live_credential_surface_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, _ = _demo_root(tmp_path, source=_SECRET_REPOSITORY_SOURCE)
    monkeypatch.setattr(_checker, "ROOT", tmp_path)
    failures = _checker.audit(
        {
            "reachable": [_demo_ledger_entry()],
            "retired": [{"path": "packages/demo/src/demo/secrets.py"}],
        },
        modules={"demo.secrets": fixture},
        reachable={"demo.secrets"},
        trusted=_ledger(),
    )
    assert any("retired credential implementation is reachable" in failure for failure in failures)
    assert any("retired credential implementation still exists" in failure for failure in failures)


def test_main_reports_each_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_checker, "audit", lambda: ["demo credential failure"])
    assert _checker.main() == 1
    assert "demo credential failure" in capsys.readouterr().err


def test_main_passes_on_the_committed_policy() -> None:
    assert _checker.main() == 0


def test_script_entrypoint_exits_zero() -> None:
    """`python scripts/check-credential-authority.py` is the CI invocation."""
    import runpy

    with pytest.raises(SystemExit) as completed:
        runpy.run_path(str(CHECKER), run_name="__main__")
    assert completed.value.code == 0
