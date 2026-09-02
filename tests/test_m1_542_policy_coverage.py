"""Branch-complete regression evidence for the #542 trusted-ratchet conversions."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_MISSING = object()


class _ProvError(RuntimeError):
    pass


class _Baseline:
    def __init__(
        self,
        payload: object = _MISSING,
        *,
        text: str | None = None,
        origin: str = "base",
        base_sha: str | None = "trusted",
        path: Path | None = None,
    ) -> None:
        self._payload = payload
        self.text = text
        self.origin = origin
        self.base_sha = base_sha
        self.path = path or Path("quality/fake.json")

    def loads(self, default: Any = None) -> Any:
        if self._payload is not _MISSING:
            return self._payload
        if self.text is None:
            return default
        return json.loads(self.text)


class _Proof:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def render(self) -> str:
        return "proof"


def _provenance(
    payload: object | Callable[[Path], object],
    *,
    authorizations: dict[str, str] | None = None,
) -> SimpleNamespace:
    def resolve(path: Path, **_kwargs: object) -> _Baseline:
        value = payload(path) if callable(payload) else payload
        return _Baseline(value, path=path)

    return SimpleNamespace(
        RatchetProvenanceError=_ProvError,
        Baseline=_Baseline,
        Provenance=_Proof,
        resolve_baseline=resolve,
        require_measurement=lambda *_args, **_kwargs: None,
        require_metric_version=lambda *_args, **_kwargs: None,
        load_authorizations=lambda *_args, **_kwargs: dict(authorizations or {}),
        head_sha=lambda *_args, **_kwargs: "candidate",
    )


def _broken_provenance() -> SimpleNamespace:
    def resolve(*_args: object, **_kwargs: object) -> _Baseline:
        raise _ProvError("trusted oracle unreadable")

    prov = _provenance({})
    prov.resolve_baseline = resolve
    return prov


def _load_script(relative: str, name: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _exercise_loader(module: ModuleType, target: Path, name: str) -> None:
    sys.modules.pop(name, None)
    first = module._load(target, name)
    assert module._load(target, name) is first


def _wire_adapter(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    checker: object,
    prov: object,
) -> None:
    monkeypatch.setattr(
        module,
        "_load",
        lambda path, _name: checker if path == module.CHECKER else prov,
    )


def test_citation_adapter_covers_success_failure_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(
        "scripts/check-citation-status-provenance.py", "_coverage_citation_adapter"
    )
    _exercise_loader(module, module.PROVENANCE, "_coverage_citation_real_provenance")
    assert module._known(None) == set()
    assert module._known({"known": "not-a-list"}) == set()

    problem = SimpleNamespace(source="doc", field_name="field", target="target")
    identity = "doc.field -> target"
    checker = SimpleNamespace(
        _corpus=lambda: [Path("doc.md")],
        check_citations=lambda _corpus: [problem],
        _load_baseline=lambda: SimpleNamespace(entries={identity}),
        LEDGER=tmp_path / "citation.json",
    )
    _wire_adapter(module, monkeypatch, checker, _provenance({"known": [identity]}))
    assert module.main() == 0

    _wire_adapter(module, monkeypatch, checker, _provenance({"known": []}))
    assert module.main() == 1

    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def test_contract_adapter_covers_success_failure_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(
        "scripts/check-contract-markers-provenance.py", "_coverage_contract_adapter"
    )
    _exercise_loader(module, module.PROVENANCE, "_coverage_contract_real_provenance")
    assert module._categories(None) == {}
    assert module._categories({"categories": []}) == {}

    class Finding:
        def as_line(self) -> str:
            return "category::gap"

    finding = Finding()
    candidate_marker = object()

    def checker_for(*, trusted_has_gap: bool) -> SimpleNamespace:
        def compare(_findings: object, baseline: object):
            if baseline is candidate_marker:
                return [], [], []
            return ([], [], []) if trusted_has_gap else ([finding], [], [])

        return SimpleNamespace(
            DOC_DIRS=[],
            BASELINE=tmp_path / "contract.json",
            collect=lambda _root: [finding],
            load_baseline=lambda _path: candidate_marker,
            compare=compare,
        )

    checker = checker_for(trusted_has_gap=True)
    payload = {"metric_definition_version": "1", "categories": {"category": {"entries": []}}}
    _wire_adapter(module, monkeypatch, checker, _provenance(payload))
    assert module.main() == 0

    checker = checker_for(trusted_has_gap=False)
    _wire_adapter(module, monkeypatch, checker, _provenance({"categories": {}}))
    assert module.main() == 1

    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def test_enumeration_adapter_covers_success_failure_unavailable_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(
        "scripts/check-enumerations-provenance.py", "_coverage_enumerations_adapter"
    )
    _exercise_loader(module, module.PROVENANCE, "_coverage_enumerations_real_provenance")

    class Gap:
        def key(self) -> str:
            return "gap"

    checker = SimpleNamespace(
        CHECKS={"one": lambda: ([Gap()], None)},
        BASELINE_PATH=tmp_path / "enumerations.json",
        load_baseline=lambda: {"gap": "candidate"},
    )
    _wire_adapter(module, monkeypatch, checker, _provenance({"tolerated": {"gap": "trusted"}}))
    assert module.main() == 0

    _wire_adapter(module, monkeypatch, checker, _provenance({"tolerated": {}}))
    assert module.main() == 1

    unavailable = SimpleNamespace(
        CHECKS={"one": lambda: ([], "scanner unavailable")},
        BASELINE_PATH=tmp_path / "enumerations.json",
        load_baseline=lambda: {},
    )
    _wire_adapter(module, monkeypatch, unavailable, _provenance({"tolerated": {}}))
    assert module.main() == 1

    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def test_lifecycle_adapter_covers_success_failure_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("scripts/check-lifecycle-provenance.py", "_coverage_lifecycle_adapter")
    _exercise_loader(module, module.PROVENANCE, "_coverage_lifecycle_real_provenance")
    assert module._violations(None) == set()
    assert module._violations({"violations": ["a"]}) == {"a"}
    assert module._violations({"violations": "bad"}) == set()
    monkeypatch.setattr(module, "_ROOTS", [])

    checker = SimpleNamespace(
        BASELINE=tmp_path / "lifecycle.json",
        collect_errors=lambda _roots: {"gap": "detail"},
        load_baseline=lambda: {"gap"},
        apply_baseline=lambda _errors, _candidate: ([], []),
    )
    _wire_adapter(module, monkeypatch, checker, _provenance({"violations": {"gap": "detail"}}))
    assert module.main() == 0

    _wire_adapter(module, monkeypatch, checker, _provenance({"violations": {}}))
    assert module.main() == 1

    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def test_promotion_adapter_covers_success_failure_missing_roots_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(
        "scripts/check-promotion-surface-provenance.py", "_coverage_promotion_adapter"
    )
    _exercise_loader(module, module.PROVENANCE, "_coverage_promotion_real_provenance")
    assert module._tolerated(None) == {}
    assert module._tolerated({"tolerated": []}) == {}

    finding = SimpleNamespace(path="a.py")

    def checker_for(*, uncovered: bool = False, missing_roots: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            BASELINE_PATH=tmp_path / "promotion.json",
            PROMOTION_ROOTS={"root"},
            index_modules=lambda: {"a.py": object()},
            audit=lambda: ([], {}),
            _missing_roots=lambda _modules: ["missing-root"] if missing_roots else [],
            reachable=lambda _roots, _modules: {"a.py"},
            _matcher=lambda: object(),
            _coverage=lambda _closure, _modules, _trusted, _matcher: (
                [finding] if uncovered else [],
                [],
                set(),
            ),
            _symlinked_sources=lambda _closure, _modules: [],
        )

    checker = checker_for()
    _wire_adapter(module, monkeypatch, checker, _provenance({"tolerated": {"a.py": "ok"}}))
    assert module.main() == 0

    checker = checker_for(uncovered=True)
    _wire_adapter(module, monkeypatch, checker, _provenance({"tolerated": {}}))
    assert module.main() == 1

    checker = checker_for(missing_roots=True)
    _wire_adapter(module, monkeypatch, checker, _provenance({"tolerated": {}}))
    assert module.main() == 1

    checker = checker_for()
    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def test_shell_adapter_covers_success_failure_bad_candidate_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("scripts/check-shell-execution-provenance.py", "_coverage_shell_adapter")
    _exercise_loader(module, module.PROVENANCE, "_coverage_shell_real_provenance")
    assert module._declared(None) == set()
    assert module._declared({"calls": {}}) == set()
    assert module._identity(("a.py", "call")) == "a.py::call"

    ledger = tmp_path / "shell.json"
    ledger.write_text(json.dumps({"calls": [{"file": "a.py", "symbol": "call"}]}))
    checker = SimpleNamespace(
        LEDGER=ledger,
        GOVERNED=[],
        discovered=lambda: {("a.py", "call")},
        audit=lambda: [],
        _is_test=lambda _path: False,
    )
    _wire_adapter(
        module,
        monkeypatch,
        checker,
        _provenance({"calls": [{"file": "a.py", "symbol": "call"}]}),
    )
    assert module.main() == 0

    _wire_adapter(module, monkeypatch, checker, _provenance({"calls": []}))
    assert module.main() == 1

    ledger.write_text("not-json", encoding="utf-8")
    assert module.main() == 1
    ledger.write_text(json.dumps({"calls": [{"file": "a.py", "symbol": "call"}]}))

    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def test_reachability_adapter_covers_success_failure_unknown_identity_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(
        "scripts/check-reachability-provenance.py", "_coverage_reachability_adapter"
    )
    _exercise_loader(module, module.PROVENANCE, "_coverage_reachability_real_provenance")
    assert module._unreachable(None) == set()
    assert module._unreachable({"unreachable": "bad"}) == set()

    ledger = tmp_path / "reachability.json"
    ledger.write_text(json.dumps({"unreachable": ["m"]}), encoding="utf-8")
    unknown: list[tuple[str, str | None]] = []
    checker = SimpleNamespace(
        ROOT=tmp_path,
        FLAT_APPS={},
        STATIC_ROOTS=set(),
        DYNAMIC_ROOTS=set(),
        BASELINE=ledger,
        _reachability=lambda *_args: ({"m": object()}, set()),
        unknown_baseline_entries=lambda _candidate, _mods: list(unknown),
    )
    _wire_adapter(module, monkeypatch, checker, _provenance({"unreachable": ["m"]}))
    assert module.main() == 0

    _wire_adapter(module, monkeypatch, checker, _provenance({"unreachable": []}))
    assert module.main() == 1

    unknown.append(("m", "module.m"))
    assert module.main() == 1
    unknown.clear()

    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def test_reachability_disposition_adapter_covers_success_failure_and_unreadable_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(
        "scripts/check-reachability-dispositions-provenance.py",
        "_coverage_reachability_disposition_adapter",
    )
    _exercise_loader(module, module.PROVENANCE, "_coverage_dispositions_real_provenance")
    assert module._unreachable(None) == set()
    assert module._disposition_modules(None) == set()
    assert module._disposition_modules({"groups": [None, {"modules": ["m"]}]}) == {"m"}

    baseline = tmp_path / "reachability.json"
    ledger = tmp_path / "dispositions.json"
    baseline.write_text(json.dumps({"unreachable": ["m"]}), encoding="utf-8")
    ledger.write_text(json.dumps({"groups": [{"modules": ["m"]}]}), encoding="utf-8")
    checker = SimpleNamespace(
        BASELINE=baseline,
        LEDGER=ledger,
        audit=lambda _payload, _baseline, _subsystems: [],
        matrix_subsystems=lambda: {},
    )

    def matching(path: Path) -> object:
        return {"unreachable": ["m"]} if path == baseline else {"groups": [{"modules": ["m"]}]}

    _wire_adapter(module, monkeypatch, checker, _provenance(matching))
    assert module.main() == 0

    def empty(path: Path) -> object:
        return {"unreachable": []} if path == baseline else {"groups": []}

    _wire_adapter(module, monkeypatch, checker, _provenance(empty))
    assert module.main() == 1

    _wire_adapter(module, monkeypatch, checker, _broken_provenance())
    assert module.main() == 1


def _exercise_direct_provenance_loader(module: ModuleType) -> None:
    sys.modules.pop("_ratchet_provenance", None)
    first = module._provenance()
    assert module._provenance() is first


def test_execution_lifecycle_main_covers_trusted_and_unauthorized_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("scripts/check-execution-lifecycles.py", "_coverage_execution_lifecycle")
    _exercise_direct_provenance_loader(module)
    ledger = tmp_path / "execution-lifecycles.json"
    ledger.write_text(
        json.dumps(
            {"lifecycles": {"m::State": {"classification": "CANONICAL", "rationale": "canonical"}}}
        )
    )
    found = {"m::State": {"PENDING", "RUNNING", "DONE"}}
    monkeypatch.setattr(module, "LEDGER", ledger)
    monkeypatch.setattr(module, "discover", lambda: found)
    monkeypatch.setattr(
        module,
        "_provenance",
        lambda: _provenance(
            {"lifecycles": {"m::State": {"classification": "CANONICAL", "rationale": "ok"}}}
        ),
    )
    assert module.main() == 0

    monkeypatch.setattr(module, "_provenance", lambda: _provenance({"lifecycles": {}}))
    assert module.main() == 1
    assert module.audit({}, found) == ["ledger has no 'lifecycles' object"]


def test_model_egress_main_covers_missing_success_and_unauthorized_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("scripts/check-model-egress.py", "_coverage_model_egress")
    _exercise_direct_provenance_loader(module)
    inventory = tmp_path / "model-egress.json"
    monkeypatch.setattr(module, "INVENTORY", inventory)
    assert module.main() == 1

    inventory.write_text(json.dumps({"modules": ["m"]}), encoding="utf-8")
    monkeypatch.setattr(module, "discover", lambda: {"m"})
    monkeypatch.setattr(module.check_direct_effects, "main", lambda _argv: 0)
    monkeypatch.setattr(module, "_provenance", lambda: _provenance({"modules": ["m"]}))
    assert module.main() == 0

    monkeypatch.setattr(module, "_provenance", lambda: _provenance({"modules": []}))
    assert module.main() == 1
    assert not module.performs_egress("not python: [")


def test_public_routes_main_covers_missing_success_and_new_surface_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("scripts/check-public-routes.py", "_coverage_public_routes")
    _exercise_direct_provenance_loader(module)
    middleware = tmp_path / "auth.py"
    registry = tmp_path / "public-routes.json"
    monkeypatch.setattr(module, "MIDDLEWARE", middleware)
    monkeypatch.setattr(module, "REGISTRY", registry)
    assert module.main() == 1

    middleware.write_text('_PUBLIC_EXACT = ("/health",)\n', encoding="utf-8")
    registry.write_text(
        json.dumps(
            {
                "routes": {
                    "/health": {
                        "kind": "exact",
                        "owner": "@owner",
                        "risk": "low",
                        "disposition": "permanent",
                        "reason": "health",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_materialize_ci_history", lambda _prov: None)
    monkeypatch.setattr(
        module,
        "_provenance",
        lambda: _provenance(
            {
                "routes": {
                    "/health": {
                        "kind": "exact",
                        "owner": "@owner",
                        "risk": "low",
                        "disposition": "permanent",
                        "reason": "health",
                    }
                }
            }
        ),
    )
    assert module.main() == 0

    monkeypatch.setattr(module, "_provenance", lambda: _provenance({"routes": {}}))
    assert module.main() == 1


def test_radon_main_covers_trusted_and_unauthorized_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script("scripts/check-radon-baseline.py", "_coverage_radon")
    _exercise_direct_provenance_loader(module)
    block = module.Block("a.py", 1, "f", None, "C", 10)
    candidate = {"entries": [{"key": block.key, "complexity": 10}]}
    monkeypatch.setattr(module, "_load_baseline", lambda: candidate)
    monkeypatch.setattr(module, "_run_radon", lambda _args: [block])
    monkeypatch.setattr(module, "_provenance", lambda: _provenance(candidate))
    assert module.main([]) == 0

    monkeypatch.setattr(module, "_provenance", lambda: _provenance({"entries": []}))
    assert module.main([]) == 1
    assert block.authorization_key.endswith("@10")
    assert "a.py:1" in block.render()


def test_vulture_main_covers_trusted_and_unauthorized_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("scripts/check-vulture-baseline.py", "_coverage_vulture")
    _exercise_direct_provenance_loader(module)
    finding = module.Finding("a.py", 1, "unused 'x'", 90)
    candidate = {
        "rules": [
            {
                "id": "r",
                "path_regex": ".*",
                "message_regex": ".*",
                "findings": [finding.stable_key],
            }
        ]
    }
    monkeypatch.setattr(module, "_load_baseline", lambda: candidate)
    monkeypatch.setattr(module, "_run_vulture", lambda _args: [finding])
    monkeypatch.setattr(module, "_provenance", lambda: _provenance(candidate))
    assert module.main(["a.py"]) == 0

    trusted = {"rules": [{"id": "r", "path_regex": ".*", "message_regex": ".*", "findings": []}]}
    monkeypatch.setattr(module, "_provenance", lambda: _provenance(trusted))
    assert module.main(["a.py"]) == 1
    assert module._source_for("definitely-missing.py") == ""
    assert module.Finding.parse("not a vulture finding") is None


def _mutation_row(source: str, outcome: str = "killed") -> str:
    return json.dumps(
        [
            {"mutations": [{"module_path": source}]},
            {"test_outcome": outcome},
        ]
    )


def test_mutation_main_covers_measurement_empty_and_write_candidate_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("scripts/check_mutation_baseline.py", "_coverage_mutation")
    _exercise_direct_provenance_loader(module)
    prov = _provenance({})
    monkeypatch.setattr(module, "_provenance", lambda: prov)

    baseline = tmp_path / "baseline.json"
    history = tmp_path / "history.json"
    rows = tmp_path / "rows.jsonl"
    baseline.write_text(json.dumps({"entries": {"pkg/mod.py": {"kill_rate": 0.9}}}))
    history.write_text(json.dumps({"entries": {}}))
    rows.write_text(_mutation_row("pkg/mod.py") + "\n", encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_HISTORY", history)

    assert module.main([str(rows), "--baseline", str(baseline)]) == 0
    assert module.main([str(rows), "--baseline", str(baseline), "--write-baseline"]) == 0

    rows.write_text("\n", encoding="utf-8")
    assert module.main([str(rows), "--baseline", str(baseline)]) == 1

    assert module._entry_rate({"kill_rate": "bad"}) is None
    assert module._measured_rate({}, "missing") is None
    assert module._new_candidate_entry_failures("m", {"kill_rate": 0.9}, None)
    assert module._trusted_entry_failures("m", {}, {}, None)


def test_ratchet_provenance_error_edges_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provenance = _load_script("scripts/ratchet_provenance.py", "_coverage_ratchet_provenance")

    with pytest.raises(provenance.RatchetProvenanceError, match="could not be read"):
        provenance._github_event_payload(str(tmp_path / "missing-event.json"))

    event = tmp_path / "event.json"
    event.write_text("[]", encoding="utf-8")
    with pytest.raises(provenance.RatchetProvenanceError, match="not a JSON object"):
        provenance._github_event_payload(str(event))

    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    assert provenance._pull_request_event_base(
        {"pull_request": {"base": {"ref": "integration"}}}
    ) == ("origin/integration")

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert provenance._github_event_base() is None

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    with pytest.raises(provenance.RatchetProvenanceError, match="could not be resolved"):
        provenance._resolve_commit("does-not-exist", root=repo)

    monkeypatch.delenv(provenance.BASE_REV_ENV, raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert provenance._base_rev(None, root=repo) is None
