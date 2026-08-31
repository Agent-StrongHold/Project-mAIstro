"""Close policy/error-path diff coverage for the #542 trusted-ratchet conversion."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


def _prov(
    payload: object = _MISSING,
    *,
    authorizations: dict[str, str] | None = None,
    resolve_error: str | None = None,
) -> SimpleNamespace:
    def resolve(path: Path, **_kwargs: object) -> _Baseline:
        if resolve_error is not None:
            raise _ProvError(resolve_error)
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


def _load(relative: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_dynamic_provenance_loaders_clean_failed_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = [
        _load("scripts/check-execution-lifecycles.py", "_edge_execution_loader"),
        _load("scripts/check-model-egress.py", "_edge_egress_loader"),
        _load("scripts/check-radon-baseline.py", "_edge_radon_loader"),
        _load("scripts/check-vulture-baseline.py", "_edge_vulture_loader"),
    ]

    class Loader:
        def exec_module(self, _module: ModuleType) -> None:
            raise RuntimeError("boom")

    for index, module in enumerate(modules):
        name = f"_failed_ratchet_provenance_{index}"
        fake_spec = SimpleNamespace(name=name, loader=Loader())
        fake_module = ModuleType(name)
        with monkeypatch.context() as patch:
            patch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args: fake_spec)
            patch.setattr(module.importlib.util, "module_from_spec", lambda _spec: fake_module)
            sys.modules.pop(name, None)
            with pytest.raises(RuntimeError, match="boom"):
                module._provenance()
            assert name not in sys.modules

    shell = _load("scripts/check-shell-execution-provenance.py", "_edge_shell_loader")
    name = "_failed_shell_dependency"
    fake_spec = SimpleNamespace(name=name, loader=Loader())
    fake_module = ModuleType(name)
    with monkeypatch.context() as patch:
        patch.setattr(shell.importlib.util, "spec_from_file_location", lambda *_args: fake_spec)
        patch.setattr(shell.importlib.util, "module_from_spec", lambda _spec: fake_module)
        sys.modules.pop(name, None)
        with pytest.raises(RuntimeError, match="boom"):
            shell._load(Path("unused.py"), name)
        assert name not in sys.modules


def test_shell_adapter_covers_measurement_and_failure_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("scripts/check-shell-execution-provenance.py", "_edge_shell_main")
    ledger = tmp_path / "shell.json"
    governed = tmp_path / "pkg"
    governed.mkdir()
    (governed / "live.py").write_text("print('x')\n", encoding="utf-8")
    (governed / "test_live.py").write_text("print('x')\n", encoding="utf-8")
    checker = SimpleNamespace(
        GOVERNED=["pkg", "missing"],
        LEDGER=ledger,
        _is_test=lambda path: path.name.startswith("test_"),
        discovered=lambda: {("a.py", "call"), ("b.py", "new")},
        audit=lambda: [],
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert [path.name for path in module._measured_files(checker)] == ["live.py"]

    def wire(prov: object) -> None:
        monkeypatch.setattr(
            module,
            "_load",
            lambda path, _name: checker if path == module.CHECKER else prov,
        )

    ledger.write_text("not-json", encoding="utf-8")
    wire(_prov({"calls": []}))
    assert module.main() == 1

    ledger.write_text(
        json.dumps(
            {
                "calls": [
                    {"file": "a.py", "symbol": "call"},
                    {"file": "stale.py", "symbol": "old"},
                ]
            }
        ),
        encoding="utf-8",
    )
    wire(_prov(resolve_error="trusted oracle unreadable"))
    assert module.main() == 1
    wire(_prov({"calls": [{"file": "a.py", "symbol": "call"}]}))
    assert module.main() == 1


def test_execution_lifecycle_main_covers_provenance_and_authorized_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("scripts/check-execution-lifecycles.py", "_edge_execution_main")
    ledger = tmp_path / "execution.json"
    monkeypatch.setattr(module, "LEDGER", ledger)
    assert module.main() == 1

    ledger.write_text(json.dumps({"lifecycles": {}}), encoding="utf-8")
    found = {"pkg::State": {"PENDING", "RUNNING", "DONE"}}
    monkeypatch.setattr(module, "discover", lambda: found)
    monkeypatch.setattr(module, "_provenance", lambda: _prov(resolve_error="bad base"))
    assert module.main() == 1

    monkeypatch.setattr(
        module,
        "_provenance",
        lambda: _prov({"lifecycles": {}}, authorizations={"pkg::State": "reviewed"}),
    )
    assert module.main() == 1
    assert module._entries(None) == {}
    assert module._entries({"lifecycles": []}) == {}


def test_model_egress_main_covers_provenance_and_candidate_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("scripts/check-model-egress.py", "_edge_model_egress")
    inventory = tmp_path / "model-egress.json"
    monkeypatch.setattr(module, "INVENTORY", inventory)
    assert module._modules(None) == set()
    assert module._modules({"modules": "bad"}) == set()

    inventory.write_text(json.dumps({"modules": ["stale"]}), encoding="utf-8")
    monkeypatch.setattr(module, "discover", lambda: {"new"})
    monkeypatch.setattr(module, "_provenance", lambda: _prov(resolve_error="bad base"))
    assert module.main() == 1

    monkeypatch.setattr(
        module,
        "_provenance",
        lambda: _prov({"modules": []}, authorizations={"new": "reviewed"}),
    )
    assert module.main() == 1


def test_public_route_git_materialization_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load("scripts/check-public-routes.py", "_edge_public_git")
    prov = SimpleNamespace(RatchetProvenanceError=_ProvError)

    with monkeypatch.context() as patch:
        patch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("git")))
        with pytest.raises(RuntimeError, match="could not run"):
            module._run_git(["status"])

    failed = subprocess.CompletedProcess([], 1, "", "nope")
    shallow = subprocess.CompletedProcess([], 0, "true\n", "")
    success = subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(module, "_run_git", lambda _args: failed)
    with pytest.raises(_ProvError, match="checkout depth"):
        module._unshallow_ci_checkout(prov, "origin/develop")

    monkeypatch.setattr(module, "_run_git", lambda _args: shallow)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    with pytest.raises(_ProvError, match="GITHUB_REF"):
        module._unshallow_ci_checkout(prov, "origin/develop")

    monkeypatch.setenv("GITHUB_REF", "refs/pull/1/merge")
    responses = iter([shallow, failed])
    monkeypatch.setattr(module, "_run_git", lambda _args: next(responses))
    with pytest.raises(_ProvError, match="could not unshallow"):
        module._unshallow_ci_checkout(prov, "origin/develop")

    monkeypatch.setattr(module, "_run_git", lambda _args: failed)
    with pytest.raises(_ProvError, match="could not materialize"):
        module._materialize_event_base(prov, "origin/develop")

    responses = iter([failed, failed])
    monkeypatch.setattr(module, "_run_git", lambda _args: next(responses))
    with pytest.raises(_ProvError, match="could not materialize"):
        module._materialize_event_base(prov, "deadbeef")

    responses = iter([success])
    monkeypatch.setattr(module, "_run_git", lambda _args: next(responses))
    module._materialize_event_base(prov, "deadbeef")


def test_public_route_main_reports_kind_change_and_provenance_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("scripts/check-public-routes.py", "_edge_public_main")
    middleware = tmp_path / "auth.py"
    registry = tmp_path / "public-routes.json"
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
    monkeypatch.setattr(module, "MIDDLEWARE", middleware)
    monkeypatch.setattr(module, "REGISTRY", registry)
    monkeypatch.setattr(module, "_materialize_ci_history", lambda _prov: None)
    monkeypatch.setattr(
        module,
        "_provenance",
        lambda: _prov(
            {
                "routes": {
                    "/health": {
                        "kind": "prefix",
                        "owner": "@owner",
                        "risk": "low",
                        "disposition": "permanent",
                        "reason": "old",
                    }
                }
            }
        ),
    )
    assert module.main() == 1

    monkeypatch.setattr(module, "_provenance", lambda: _prov(resolve_error="bad route base"))
    assert module.main() == 1


def test_radon_error_and_authorized_banking_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("scripts/check-radon-baseline.py", "_edge_radon_main")
    failed = subprocess.CompletedProcess([], 7, "stdout", "stderr")
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: failed)
    with pytest.raises(SystemExit) as exc:
        module._run_radon(["pkg"])
    assert exc.value.code == 7

    baseline = tmp_path / "radon.json"
    baseline.write_text(json.dumps({"entries": []}), encoding="utf-8")
    monkeypatch.setattr(module, "BASELINE", baseline)
    block = module.Block("a.py", 1, "f", None, "C", 10)
    monkeypatch.setattr(module, "_run_radon", lambda _args: [block])
    monkeypatch.setattr(module, "_provenance", lambda: _prov([]))
    assert module.main([]) == 1

    monkeypatch.setattr(
        module,
        "_provenance",
        lambda: _prov({"entries": []}, authorizations={block.authorization_key: "reviewed"}),
    )
    assert module.main([]) == 1


def test_vulture_error_update_and_trusted_state_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("scripts/check-vulture-baseline.py", "_edge_vulture_main")
    failed = subprocess.CompletedProcess([], 9, "stdout", "stderr")
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: failed)
    with pytest.raises(SystemExit) as exc:
        module._run_vulture(["pkg"])
    assert exc.value.code == 9

    finding = module.Finding("a.py", 1, "unused 'x'", 90)
    dirty = module.Classification({"r": []}, [finding], [])
    assert module._candidate_has_unbankable_findings(dirty, update=True)

    with pytest.raises(_ProvError, match="trusted ledger is not a JSON object"):
        module._trusted_state([finding], _prov([]))

    monkeypatch.setattr(module, "_provenance", lambda: _prov(resolve_error="bad vulture base"))
    clean = module.Classification({"r": []}, [], [])
    assert module._enforce_trusted([], [{"id": "r", "findings": []}], clean) == 1

    baseline = {"rules": [{"id": "r", "path_regex": ".*", "message_regex": ".*", "findings": []}]}
    wrote: list[bool] = []
    monkeypatch.setattr(module, "_load_baseline", lambda: baseline)
    monkeypatch.setattr(module, "_run_vulture", lambda _args: [])
    monkeypatch.setattr(module, "_write_baseline", lambda *_args: wrote.append(True))
    assert module.main(["--update"]) == 0
    assert wrote == [True]


def test_mutation_entry_validation_edges(tmp_path: Path) -> None:
    module = _load("scripts/check_mutation_baseline.py", "_edge_mutation_validation")
    assert module._trusted_entry_failures("a", {}, {}, 0.9)
    assert module._trusted_entry_failures(
        "a", {"kill_rate": 0.9}, {"kill_rate": 0.8}, 0.8
    )
    assert module._trusted_entry_failures(
        "a", {"kill_rate": 0.9}, {"kill_rate": 1.0}, 0.9
    )
    assert module._new_candidate_entry_failures("a", {"kill_rate": 0.9}, None)
    assert module._new_candidate_entry_failures("a", {}, 0.9)
    assert module._new_candidate_entry_failures("a", {"kill_rate": 0.8}, 0.9)

    failures = module.candidate_baseline_failures(
        {"new": (9, 10)},
        {"entries": {"trusted": {"kill_rate": 0.9}}},
        {"entries": {"new": {"kill_rate": 0.8}}},
    )
    assert any("removed a trusted source floor" in failure for failure in failures)
    assert any("must equal measured" in failure for failure in failures)

    external = tmp_path / "external.json"
    external.write_text("[]", encoding="utf-8")
    with pytest.raises(_ProvError, match="not a JSON object"):
        module._trusted_json(external, prov=_prov())


def test_mutation_health_report_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load("scripts/check_mutation_baseline.py", "_edge_mutation_publish")
    rows = tmp_path / "rows.jsonl"
    json_report = tmp_path / "mutation-health-report.json"
    md_report = tmp_path / "mutation-health-report.md"
    json_report.write_text(json.dumps({"existing": True}), encoding="utf-8")
    md_report.write_text("# Existing\n", encoding="utf-8")
    fake = SimpleNamespace(render_markdown=lambda report: f"ratchet={report['ok']}")
    monkeypatch.setitem(sys.modules, "mutation_ratchet", fake)

    module._publish_ratchet_into_health_report(rows, {"ok": True})
    assert json.loads(json_report.read_text())["ratchet"] == {"ok": True}
    assert "ratchet=True" in md_report.read_text()


def test_mutation_scheduler_candidate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load("scripts/check_mutation_baseline.py", "_edge_mutation_scheduler")
    rows = tmp_path / "rows.jsonl"
    rows.write_text("", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    telemetry = tmp_path / "mutation-telemetry-all.jsonl"
    telemetry.write_text("{}\n", encoding="utf-8")
    fake = SimpleNamespace(
        read_telemetry=lambda _path: {"a.py": {"runtime": 1}},
        evaluate=lambda *_args, **_kwargs: {
            "quality_failures": ["a.py failed"],
            "runtime_regressions": [],
            "newly_surviving": [],
        },
        baseline_candidate=lambda *_args, **_kwargs: {"entries": {"a.py": {"kill_rate": 0.9}}},
        render_markdown=lambda _report: "ratchet",
    )
    monkeypatch.setitem(sys.modules, "mutation_ratchet", fake)
    monkeypatch.setattr(module, "_publish_ratchet_into_health_report", lambda *_args: None)

    prov = _prov()
    assert (
        module._write_scheduler_candidate(
            rows,
            baseline,
            trusted_baseline={"entries": {}},
            trusted_history={"entries": {}},
            provenance=_Baseline({"entries": {}}),
            prov=prov,
        )
        == 1
    )
    assert json.loads(baseline.read_text())["entries"]["a.py"]["kill_rate"] == 0.9

    telemetry.unlink()
    with pytest.raises(ValueError, match="telemetry not found"):
        module._write_scheduler_candidate(
            rows,
            baseline,
            trusted_baseline={"entries": {}},
            trusted_history={"entries": {}},
            provenance=_Baseline({"entries": {}}),
            prov=prov,
        )


def test_mutation_main_fail_closed_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load("scripts/check_mutation_baseline.py", "_edge_mutation_main")
    rows = tmp_path / "rows.jsonl"
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    prov = _prov()
    monkeypatch.setattr(module, "_provenance", lambda: prov)

    def bad_trusted(*_args: object, **_kwargs: object):
        raise _ProvError("bad mutation base")

    monkeypatch.setattr(module, "_trusted_json", bad_trusted)
    rows.write_text("", encoding="utf-8")
    assert module.main([str(rows), "--baseline", str(baseline)]) == 2

    monkeypatch.setattr(
        module,
        "_trusted_json",
        lambda path, **_kwargs: ({"entries": {}}, _Baseline({"entries": {}}, path=path)),
    )
    assert module.main([str(rows), "--baseline", str(baseline)]) == 1

    rows.write_text(
        json.dumps(
            [
                {"mutations": [{"module_path": "a.py"}]},
                {"test_outcome": "killed"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    failing_prov = _prov()
    failing_prov.require_measurement = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        _ProvError("measurement unavailable")
    )
    monkeypatch.setattr(module, "_provenance", lambda: failing_prov)
    assert module.main([str(rows), "--baseline", str(baseline)]) == 2

    monkeypatch.setattr(module, "_provenance", lambda: prov)
    monkeypatch.setattr(module, "_inside_repository", lambda _path: True)
    monkeypatch.setattr(
        module,
        "_candidate_json",
        lambda _path: (_ for _ in ()).throw(ValueError("candidate malformed")),
    )
    assert module.main([str(rows), "--baseline", str(baseline)]) == 2
