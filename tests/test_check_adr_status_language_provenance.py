"""The absence metric cannot relabel trusted debt or authorize itself."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import ratchet_provenance as provenance

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-adr-status-language-provenance.py"
IDENTITY = "docs/adr/nested/ADR-example.md :: body-status-line"


@pytest.fixture
def adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("_status_metric_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"metric_definition_version": "2", "known": [], "details": {}}))
    docs = tmp_path / "docs"
    nested = docs / "nested"
    nested.mkdir(parents=True)
    (nested / "ADR-example.md").write_text("a measured nested document\n")
    (docs / "ADR-top.md").write_text("a measured top-level document\n")
    state = {
        "trusted": {"metric_definition_version": "2", "known": [], "details": {}},
        "found": [],
        "grants": {},
    }

    def resolve(path, **_kwargs):
        payload = state["trusted"]
        return provenance.Baseline(
            text=None if payload is None else json.dumps(payload),
            origin="base",
            base_sha="a" * 40,
            path=path,
        )

    def grants(_ratchet, *, base):
        assert base == "a" * 40, "authorization must come from the trusted base"
        return state["grants"]

    checker = SimpleNamespace(
        METRIC_DEFINITION_VERSION="2",
        DOC_ROOTS=(docs,),
        LEDGER=ledger,
        audit=lambda: [SimpleNamespace(identity=identity) for identity in state["found"]],
        _load_baseline=lambda: frozenset(json.loads(ledger.read_text()).get("known", [])),
    )
    prov = SimpleNamespace(
        RatchetProvenanceError=provenance.RatchetProvenanceError,
        Provenance=provenance.Provenance,
        resolve_baseline=resolve,
        require_measurement=provenance.require_measurement,
        require_metric_version=provenance.require_metric_version,
        load_authorizations=grants,
        head_sha=lambda _root: "b" * 40,
    )
    monkeypatch.setattr(
        module, "_load", lambda path, _name: checker if path == module.CHECKER else prov
    )
    return module, ledger, state


def test_version_two_measures_nested_only_corpus(adapter, capsys) -> None:
    module, _ledger, _state = adapter
    checker = module._load(module.CHECKER, "checker")
    (checker.DOC_ROOTS[0] / "ADR-top.md").unlink()
    assert len(module._corpus(checker)) == 1
    assert module.main() == 0
    assert "metric v2" in capsys.readouterr().out


@pytest.mark.parametrize("version", [None, "1", "3"])
def test_candidate_must_record_the_current_metric(adapter, version, capsys) -> None:
    module, ledger, _state = adapter
    payload = {"known": [], "details": {}}
    if version is not None:
        payload["metric_definition_version"] = version
    ledger.write_text(json.dumps(payload))
    assert module.main() == 1
    assert "candidate ledger must record" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["1", "3"])
def test_recorded_trusted_metric_mismatch_fails_closed(adapter, version, capsys) -> None:
    module, _ledger, state = adapter
    state["trusted"]["metric_definition_version"] = version
    assert module.main() == 1
    assert "trusted floor measures a different question" in capsys.readouterr().err


def test_empty_unversioned_legacy_ledger_migrates_explicitly(adapter, capsys) -> None:
    module, _ledger, state = adapter
    state["trusted"] = {"known": [], "details": {}}
    assert module.main() == 0
    assert "explicit zero-tolerance migration to v2" in capsys.readouterr().out


@pytest.mark.parametrize(
    "legacy",
    [
        {"known": [IDENTITY], "details": {}},
        {"known": [], "details": {IDENTITY: "stale debt"}},
        {"known": []},
        {"known": "not a list", "details": {}},
        {},
        [],
    ],
)
def test_nonempty_or_malformed_unversioned_ledger_cannot_migrate(adapter, legacy, capsys) -> None:
    module, _ledger, state = adapter
    state["trusted"] = legacy
    assert module.main() == 1
    assert "only an explicitly empty unversioned legacy ledger" in capsys.readouterr().err


def test_v2_candidate_cannot_bank_an_unapproved_expansion(adapter, capsys) -> None:
    module, ledger, state = adapter
    state["trusted"] = {"known": [], "details": {}}
    state["found"] = [IDENTITY]
    ledger.write_text(json.dumps({"metric_definition_version": "2", "known": [IDENTITY]}))
    assert module.main() == 1
    assert "absent from trusted base and not previously authorized" in capsys.readouterr().err


def test_v2_still_requires_the_exact_prior_base_grant(adapter) -> None:
    module, ledger, state = adapter
    state["found"] = [IDENTITY]
    state["grants"] = {IDENTITY: "reviewed prior-base authorization"}
    ledger.write_text(json.dumps({"metric_definition_version": "2", "known": [IDENTITY]}))
    assert module.main() == 0


def test_first_introduction_keeps_its_existing_reviewed_ledger_rule(adapter) -> None:
    module, ledger, state = adapter
    state["trusted"] = None
    state["found"] = [IDENTITY]
    ledger.write_text(json.dumps({"metric_definition_version": "2", "known": [IDENTITY]}))
    assert module.main() == 0
