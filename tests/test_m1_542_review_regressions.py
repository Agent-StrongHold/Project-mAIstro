"""Regression proofs for the Codex review of trusted ratchet provenance (#542)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_script(relative: str, name: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def inventory() -> ModuleType:
    return _load_script("scripts/check-ratchet-provenance.py", "_m1_542_inventory")


@pytest.fixture(scope="module")
def enumerations_adapter() -> ModuleType:
    return _load_script(
        "scripts/check-enumerations-provenance.py", "_m1_542_enumerations_adapter"
    )


@pytest.fixture(scope="module")
def public_routes() -> ModuleType:
    return _load_script("scripts/check-public-routes.py", "_m1_542_public_routes")


@pytest.fixture(scope="module")
def mutation_gate() -> ModuleType:
    return _load_script("scripts/check_mutation_baseline.py", "_m1_542_mutation_gate")


def test_inventory_discovers_quality_consumers_under_tools(inventory, tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "lint_lifecycle.py").write_text(
        "from pathlib import Path\n"
        'BASELINE = Path(__file__).resolve().parents[1] / "quality" / "lifecycle-baseline.json"\n',
        encoding="utf-8",
    )

    assert inventory.Consumer(
        "tools/lint_lifecycle.py", "quality/lifecycle-baseline.json"
    ) in inventory.consumers(tmp_path)


def test_stale_trusted_adapter_mapping_is_a_failure(inventory) -> None:
    errors = inventory.stale_mapping_errors(
        set(),
        {("vanished.py", "quality/vanished.json"): "adapter"},
        label="trusted adapter",
    )

    assert errors == [
        "stale trusted adapter mapping vanished.py -> quality/vanished.json: adapter"
    ]


def test_lifecycle_consumer_has_a_real_trusted_adapter(inventory, tmp_path: Path) -> None:
    key = ("tools/lint_lifecycle.py", "quality/lifecycle-baseline.json")
    adapter = inventory.TRUSTED_ADAPTERS[key]

    assert adapter == "check-lifecycle-provenance"
    assert inventory._adapter_problem(ROOT, adapter) is None

    trusted = tmp_path / "trusted.py"
    trusted.write_text(
        "import ratchet_provenance\n"
        "def load(): return ratchet_provenance.load_authorizations('example')\n",
        encoding="utf-8",
    )
    assert inventory._uses_trusted_resolver(trusted)

    assert (
        "check-branch-independence.py",
        "quality/branch-independence.json",
    ) in inventory.CANDIDATE_AUTHORED
    assert (
        "check_direct_effects.py",
        "quality/direct-effect-call-sites.json",
    ) in inventory.CANDIDATE_AUTHORED


def test_github_event_metadata_supplies_every_integration_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.ratchet_provenance as provenance

    monkeypatch.delenv(provenance.BASE_REV_ENV, raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_BASE_REF", "integration")
    assert provenance._github_event_base() == "origin/integration"

    event = tmp_path / "event.json"
    event.write_text(json.dumps({"merge_group": {"base_sha": "a" * 40}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    assert provenance._github_event_base() == "a" * 40

    event.write_text(json.dumps({"before": "b" * 40}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert provenance._github_event_base() == "b" * 40


class _FakeProvenanceError(RuntimeError):
    pass


class _FakeBaseline:
    base_sha = "trusted"

    def loads(self, default=None):
        return {"tolerated": {}}


class _Proof:
    def __init__(self, **_kwargs) -> None:
        pass

    def render(self) -> str:
        return "proof"


def test_enumeration_ratchet_can_reach_zero_debt(
    enumerations_adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = SimpleNamespace(
        CHECKS={"synthetic": lambda: ([], None)},
        BASELINE_PATH=Path("quality/enumeration-baseline.json"),
        load_baseline=lambda: {},
    )

    def require_measurement(measured, **_kwargs) -> None:
        if not measured:
            raise _FakeProvenanceError("empty measurement")

    provenance = SimpleNamespace(
        RatchetProvenanceError=_FakeProvenanceError,
        resolve_baseline=lambda *_args, **_kwargs: _FakeBaseline(),
        require_measurement=require_measurement,
        load_authorizations=lambda *_args, **_kwargs: {},
        Provenance=_Proof,
        head_sha=lambda *_args, **_kwargs: "candidate",
    )
    monkeypatch.setattr(
        enumerations_adapter,
        "_load",
        lambda path, _name: checker if path == enumerations_adapter.CHECKER else provenance,
    )

    assert enumerations_adapter.main() == 0


def test_public_route_matching_kind_change_requires_prior_authorization(
    public_routes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    middleware = tmp_path / "auth.py"
    middleware.write_text('_PUBLIC_PREFIXES_LOOSE = ("/health",)\n', encoding="utf-8")
    candidate_registry = {
        "routes": {
            "/health": {
                "kind": "loose-prefix",
                "owner": "@owner",
                "risk": "low",
                "disposition": "permanent",
                "reason": "health endpoint",
            }
        }
    }
    registry = tmp_path / "public-routes.json"
    registry.write_text(json.dumps(candidate_registry), encoding="utf-8")
    trusted = {
        "routes": {
            "/health": {
                "kind": "prefix",
                "owner": "@owner",
                "risk": "low",
                "disposition": "permanent",
                "reason": "health endpoint",
            }
        }
    }

    class TrustedRoutes(_FakeBaseline):
        def loads(self, default=None):
            return trusted

    provenance = SimpleNamespace(
        RatchetProvenanceError=_FakeProvenanceError,
        resolve_baseline=lambda *_args, **_kwargs: TrustedRoutes(),
        require_measurement=lambda *_args, **_kwargs: None,
        load_authorizations=lambda *_args, **_kwargs: {},
        Provenance=_Proof,
        head_sha=lambda *_args, **_kwargs: "candidate",
    )
    monkeypatch.setattr(public_routes, "MIDDLEWARE", middleware)
    monkeypatch.setattr(public_routes, "REGISTRY", registry)
    monkeypatch.setattr(public_routes, "_provenance", lambda: provenance)

    assert public_routes.main() == 1


def test_mutation_candidate_cannot_lower_a_trusted_floor(mutation_gate) -> None:
    current = {"pkg/mod.py": (19, 20)}
    trusted = {"entries": {"pkg/mod.py": {"kill_rate": 0.95}}}
    candidate = {"entries": {"pkg/mod.py": {"kill_rate": 0.90}}}

    failures = mutation_gate.candidate_baseline_failures(current, trusted, candidate)

    assert failures == ["pkg/mod.py: candidate kill_rate 90.0% weakens trusted 95.0%"]


def test_external_mutation_baseline_remains_an_explicit_local_input(
    mutation_gate, tmp_path: Path
) -> None:
    import scripts.ratchet_provenance as provenance

    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"entries": {"pkg/mod.py": {"kill_rate": 0.91}}}), encoding="utf-8"
    )

    loaded, reference = mutation_gate._trusted_json(baseline, prov=provenance)

    assert loaded["entries"]["pkg/mod.py"]["kill_rate"] == 0.91
    assert reference.origin == "worktree"
    assert reference.base_sha is None
