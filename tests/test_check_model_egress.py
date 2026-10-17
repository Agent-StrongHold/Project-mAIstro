"""Tests for the direct-model-egress inventory gate (#36, invariant 2).

The invariant is "no direct provider bypass outside approved Provider
implementations", and it cannot be enforced as written yet: `maistro.providers`
is a registry with no HTTP client, so nothing is the approved implementation.
What can be enforced is that the set of direct callers does not grow. These pin
that, and pin the detection boundary — a module that merely names an endpoint
path for routing must not count, or the inventory fills with modules nobody can
migrate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-model-egress.py"

CALLER = """
import httpx

async def ask(client: httpx.AsyncClient) -> None:
    await client.post("https://gw/v1/chat/completions", json={})
"""


@pytest.fixture(scope="module")
def gate():
    # The gate owns its sibling dependency: `_load_direct_effects()` loads
    # `check_direct_effects` by absolute path, so the load below needs no
    # `scripts/` entry on sys.path -- and this fixture deliberately does not
    # add one (#1115). A bare sibling import reintroduced into the gate must
    # fail this isolated run instead of silently passing on a mutated
    # sys.path; that is the order-independence contract under test.
    spec = importlib.util.spec_from_file_location("check_model_egress", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- detection ----------------------------------------------------------------


def test_the_sibling_loader_loads_cold_and_caches_the_result(
    gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing cached, ``_load_direct_effects`` performs the real load.

    Every in-suite import takes the cache-hit path because an alphabetically
    earlier test module registers ``check_direct_effects`` first; this drives
    the spec-based load that path skips, which is the code that has to work
    when this gate is imported on its own.
    """
    monkeypatch.delitem(sys.modules, "check_direct_effects", raising=False)

    module = gate._load_direct_effects()

    assert module.__name__ == "check_direct_effects"
    assert sys.modules["check_direct_effects"] is module


def test_the_sibling_loader_cleans_up_a_failed_load(gate, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sibling whose exec fails must not leave its half-built module cached.

    A cached failed module would make every later importer see the broken
    object instead of the error, turning one load failure into a confused
    downstream crash.
    """
    monkeypatch.delitem(sys.modules, "check_direct_effects", raising=False)

    class Loader:
        def exec_module(self, _module: object) -> None:
            raise RuntimeError("boom")

    fake_spec = SimpleNamespace(name="check_direct_effects", loader=Loader())
    monkeypatch.setattr(gate.importlib.util, "spec_from_file_location", lambda *_args: fake_spec)
    monkeypatch.setattr(
        gate.importlib.util, "module_from_spec", lambda _spec: ModuleType("check_direct_effects")
    )

    with pytest.raises(RuntimeError, match="boom"):
        gate._load_direct_effects()

    assert "check_direct_effects" not in sys.modules


def test_a_module_that_posts_to_a_completions_endpoint_counts(gate) -> None:
    assert gate.performs_egress(CALLER)


def test_naming_the_path_without_calling_out_does_not_count(gate) -> None:
    """`maistro.auth.middleware` and `maistro.events.bus` name a completions
    path to route or allowlist it. Counting those would fill the inventory with
    modules that have nothing to migrate."""
    source = """
PUBLIC_PATHS = {"/v1/chat/completions"}

def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS
"""
    assert not gate.performs_egress(source)


def test_an_http_call_to_something_else_does_not_count(gate) -> None:
    source = """
import httpx

async def fetch(client: httpx.AsyncClient) -> None:
    await client.post("https://example.com/webhook", json={})
"""
    assert not gate.performs_egress(source)


def test_a_streaming_call_counts(gate) -> None:
    source = CALLER.replace("client.post(", "client.stream(")
    assert gate.performs_egress(source)


def test_syntax_errors_do_not_crash_detection(gate) -> None:
    assert not gate.performs_egress('"/v1/chat/completions"\ndef (:')


# --- ratchet ------------------------------------------------------------------


def test_matching_the_inventory_passes(gate) -> None:
    assert gate.audit({"a.b"}, {"a.b"}) == []


def test_a_new_direct_caller_fails_by_name(gate) -> None:
    failures = gate.audit({"a.b"}, {"a.b", "c.d"})
    assert any("c.d" in f and "may not grow" in f for f in failures)


def test_a_module_that_stopped_calling_out_must_be_pruned(gate) -> None:
    """The shrinking half. Migrating one under #56 has to take its line with it,
    or the inventory keeps a slot a later regression could occupy silently."""
    failures = gate.audit({"a.b", "gone.away"}, {"a.b"})
    assert any("gone.away" in f and "prune it" in f for f in failures)


# --- physical-egress precision and the reachability join (#1089) --------------


class _StubProof:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def render(self) -> str:
        return "proof"


class _StubBaseline:
    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.base_sha = "trusted"
        self.origin = "base"

    def loads(self, default: object = None) -> object:
        return self._payload if self._payload is not None else default


class _StubError(RuntimeError):
    pass


def _stub_provenance(
    payload: object, authorizations: dict[str, str] | None = None
) -> SimpleNamespace:
    def resolve(_path: Path, **_kwargs: object) -> _StubBaseline:
        return _StubBaseline(payload)

    return SimpleNamespace(
        RatchetProvenanceError=_StubError,
        Baseline=_StubBaseline,
        Provenance=_StubProof,
        resolve_baseline=resolve,
        require_measurement=lambda *_args, **_kwargs: None,
        require_metric_version=lambda *_args, **_kwargs: None,
        load_authorizations=lambda *_args, **_kwargs: dict(authorizations or {}),
        head_sha=lambda *_args, **_kwargs: "candidate",
    )


def test_the_shipped_chat_completions_route_is_not_physical_egress(gate) -> None:
    """The exact false positive the issue names: endpoint prose plus a route
    ``.post`` must not classify a module whose model dispatch goes through the
    Container. Its ledger row was the v1 detector lying."""
    source = (
        ROOT / "packages/maistro-server/src/maistro_server/api/chat_completions.py"
    ).read_text()
    assert gate.find_egress_sites(source) == ()
    assert not gate.performs_egress(source)


def test_a_route_post_plus_endpoint_prose_does_not_count(gate) -> None:
    """The equivalent minimal fixture: a FastAPI route registration and
    response-shape text name the endpoint but perform no HTTP."""
    source = '''
from fastapi import APIRouter

router = APIRouter(prefix="/v1")


@router.post("/v1/chat/completions")
async def chat_completions() -> dict:
    """Mirrors OpenAI's /v1/chat/completions response shape."""
    return {"choices": []}
'''
    assert not gate.performs_egress(source)


def test_a_bound_url_constant_still_counts(gate) -> None:
    """Call-site detection resolves string bindings: a module-level URL
    constant posted by a client call is physical egress (the shape
    check-m1-convergence-freeze.py pins through this detector)."""
    source = """
ENDPOINT = "/v1/chat/completions"
client.post(ENDPOINT)
"""
    assert gate.performs_egress(source)


def test_an_fstring_url_still_counts(gate) -> None:
    source = """
base = "https://gw/v1"


async def call(client) -> None:
    await client.post(f"{base}/chat/completions", json={})
"""
    assert gate.performs_egress(source)


def test_find_egress_sites_names_the_actual_call(gate) -> None:
    source = """
import httpx


async def ask(client: httpx.AsyncClient) -> None:
    await client.post("https://gw/v1/chat/completions", json={})
"""
    (site,) = gate.find_egress_sites(source, path="x.py")
    assert site.qualname == "ask"
    assert site.callee == "client.post"
    assert site.line == 6
    assert site.category == "MODEL_EFFECT"


def test_image_model_http_is_not_this_ledger_s_population(gate) -> None:
    """The census curates image-model rows separately; the trusted base here
    never recorded them. Dropping them from the population is scoping, not
    blindness -- their call sites stay dispositioned in
    quality/direct-effect-call-sites.json, and the carve-out is named."""
    expected_image_exclusions = frozenset(
        {
            "cloudflare-image-http",
            "azure-openai-image-http",
            "gemini-image-http",
            "openai-compatible-image-http",
        }
    )
    image_exclusions = gate._IMAGE_HTTP_ENTRY_POINTS
    assert image_exclusions == expected_image_exclusions


def test_the_shipped_approved_provider_boundary_performs_physical_egress(gate) -> None:
    source = (
        ROOT / "packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py"
    ).read_text()
    assert gate.performs_egress(source)


def test_the_approved_provider_boundary_is_explicit(gate) -> None:
    """Recognition is a named, reviewed constant -- not silence, and not a
    set a stray import widens."""
    expected_boundary = frozenset({"maistro.capabilities.providers.llm_gateway"})
    boundaries = gate.APPROVED_PROVIDER_BOUNDARIES
    assert boundaries == expected_boundary


def test_the_provider_boundary_is_classified_as_the_terminal_boundary(gate) -> None:
    finding = gate.EgressFinding(
        module="maistro.capabilities.providers.llm_gateway",
        identity="maistro.capabilities.providers.llm_gateway",
        sites=(),
    )
    assert gate.classify(finding, unreachable=frozenset()) == gate.PROVIDER_BOUNDARY


def test_a_baseline_unreachable_caller_is_classified_separately(gate) -> None:
    finding = gate.EgressFinding(
        module="services.canonical_corpus",
        identity="@flat/hive-conductor/services.canonical_corpus",
        sites=(),
    )
    assert (
        gate.classify(
            finding,
            unreachable=frozenset({"@flat/hive-conductor/services.canonical_corpus"}),
        )
        == gate.UNREACHABLE_LIBRARY
    )


def test_a_reachable_caller_is_the_escape_class(gate) -> None:
    finding = gate.EgressFinding(
        module="services.chat_completion",
        identity="@flat/hive-conductor/services.chat_completion",
        sites=(),
    )
    assert gate.classify(finding, unreachable=frozenset()) == gate.REACHABLE_ESCAPE


def test_report_rows_attach_the_reviewed_reachability_disposition(gate) -> None:
    finding = gate.EgressFinding(
        module="services.canonical_corpus",
        identity="@flat/hive-conductor/services.canonical_corpus",
        sites=(),
    )
    reviewed = {
        "@flat/hive-conductor/services.canonical_corpus": {
            "disposition": "CONNECT",
            "subsystem": "Agent Conductor services",
            "root": "main.py route registration",
        }
    }
    (row,) = gate._report_rows(
        {"services.canonical_corpus": finding},
        unreachable=frozenset({"@flat/hive-conductor/services.canonical_corpus"}),
        reviewed=reviewed,
    )
    assert row["disposition"] == gate.UNREACHABLE_LIBRARY
    assert row["reviewed_disposition"] == reviewed[finding.identity]


def test_a_missing_reachability_baseline_fails_closed(gate, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="reachability"):
        gate._unreachable_identities(tmp_path / "absent.json")
    with pytest.raises(RuntimeError, match="reachability"):
        gate._reviewed_dispositions(tmp_path / "absent.json")


def test_a_malformed_reachability_baseline_fails_closed(gate, tmp_path: Path) -> None:
    baseline = tmp_path / "reachability-baseline.json"
    baseline.write_text(json.dumps({"unreachable": "not-a-list"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreachable"):
        gate._unreachable_identities(baseline)


def test_a_boundary_claim_cannot_authorize_a_new_caller(
    gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adding an escape to APPROVED_PROVIDER_BOUNDARIES relabels the report;
    the ratchet still fails it, because authorization lives in the merge-base
    grants file and nowhere else."""
    inventory = tmp_path / "model-egress.json"
    inventory.write_text(
        json.dumps({"modules": [], "metric_definition_version": "2"}), encoding="utf-8"
    )
    finding = gate.EgressFinding("cunning.escape", "cunning.escape", ())
    monkeypatch.setattr(gate, "INVENTORY", inventory)
    monkeypatch.setattr(gate, "discover_sites", lambda: {"cunning.escape": finding})
    monkeypatch.setattr(gate, "APPROVED_PROVIDER_BOUNDARIES", frozenset({"cunning.escape"}))
    monkeypatch.setattr(gate, "_provenance", lambda: _stub_provenance({"modules": []}))
    monkeypatch.setattr(gate.check_direct_effects, "main", lambda _argv: 0)

    assert gate.main() == 1


def test_a_stale_ledger_entry_fails_the_gate(
    gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When physical egress disappears the recorded row must go with it --
    the shrinking half of the ratchet, end to end."""
    inventory = tmp_path / "model-egress.json"
    inventory.write_text(
        json.dumps({"modules": ["gone.caller"], "metric_definition_version": "2"}),
        encoding="utf-8",
    )
    finding = gate.EgressFinding("live.caller", "live.caller", ())
    monkeypatch.setattr(gate, "INVENTORY", inventory)
    monkeypatch.setattr(gate, "discover_sites", lambda: {"live.caller": finding})
    monkeypatch.setattr(gate, "_provenance", lambda: _stub_provenance({"modules": ["gone.caller"]}))

    assert gate.main() == 1


def test_the_report_flag_writes_machine_readable_evidence(
    gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory = tmp_path / "model-egress.json"
    inventory.write_text(
        json.dumps({"modules": ["live.caller"], "metric_definition_version": "2"}),
        encoding="utf-8",
    )
    finding = gate.EgressFinding("live.caller", "live.caller", ())
    report = tmp_path / "egress-report.json"
    monkeypatch.setattr(gate, "INVENTORY", inventory)
    monkeypatch.setattr(gate, "discover_sites", lambda: {"live.caller": finding})
    monkeypatch.setattr(gate, "_provenance", lambda: _stub_provenance({"modules": ["live.caller"]}))
    monkeypatch.setattr(gate.check_direct_effects, "main", lambda _argv: 0)

    assert gate.main(["--report", str(report)]) == 0

    payload = json.loads(report.read_text())
    assert payload["metric_definition_version"] == gate.METRIC_DEFINITION_VERSION
    (caller,) = payload["callers"]
    assert caller["module"] == "live.caller"
    assert caller["disposition"] == gate.REACHABLE_ESCAPE
    assert payload["counts"][gate.REACHABLE_ESCAPE] == 1


def test_discover_sites_surfaces_reachability_classes_from_the_shipped_tree(
    gate,
) -> None:
    """The closeout view on the real repository: the Provider boundary is the
    terminal boundary, reviewed-unreachable callers are separable from shipped
    escapes, and no caller is invisible."""
    findings = gate.discover_sites()
    unreachable = gate._unreachable_identities()

    gateway = findings["maistro.capabilities.providers.llm_gateway"]
    assert gate.classify(gateway, unreachable=unreachable) == gate.PROVIDER_BOUNDARY
    assert any(site.qualname == "execute_model_chat" for site in gateway.sites)

    corpus = findings["services.canonical_corpus"]
    assert gate.classify(corpus, unreachable=unreachable) == gate.UNREACHABLE_LIBRARY

    chat = findings["services.chat_completion"]
    assert gate.classify(chat, unreachable=unreachable) == gate.REACHABLE_ESCAPE


def test_the_route_module_false_positive_is_pruned_from_the_ledger(gate) -> None:
    payload = json.loads((ROOT / "quality" / "model-egress.json").read_text())
    assert "maistro_server.api.chat_completions" not in payload["modules"]


# --- migrations ---------------------------------------------------------------


def test_a_migration_is_recognized_only_between_recorded_and_pruned(gate) -> None:
    """The one shape the exception permits: the trusted base recorded the
    predecessor, and the candidate inventory no longer does."""
    assert (
        gate._migration_predecessor(
            "services.legacy_dag_node",
            trusted={"services.graph_runner"},
            candidate={"services.legacy_dag_node"},
        )
        == "services.graph_runner"
    )


def test_a_module_with_no_recorded_predecessor_is_not_a_migration(gate) -> None:
    """A brand-new direct caller has nothing to have moved from; it still
    needs an already-landed authorization, not a mapping entry."""
    assert (
        gate._migration_predecessor(
            "services.brand_new", trusted={"services.graph_runner"}, candidate=set()
        )
        is None
    )


def test_a_migration_needs_its_predecessor_in_the_trusted_base(gate) -> None:
    """A rename cannot import an egress the trusted base never recorded."""
    assert (
        gate._migration_predecessor(
            "services.legacy_dag_node", trusted=set(), candidate={"services.legacy_dag_node"}
        )
        is None
    )


def test_a_migration_requires_the_predecessor_to_be_pruned(gate) -> None:
    """Both modules calling out is growth, not a move. Leaving the predecessor
    banked while adding its successor must not ride the exception."""
    assert (
        gate._migration_predecessor(
            "services.legacy_dag_node",
            trusted={"services.graph_runner"},
            candidate={"services.graph_runner", "services.legacy_dag_node"},
        )
        is None
    )


def test_the_shipped_migration_map_is_the_one_reviewed_move(gate) -> None:
    """The exception is scoped per move, like CANDIDATE_AUTHORED: an entry
    nobody reviewed landing here would widen it silently."""
    assert gate.CANDIDATE_MIGRATIONS == {
        "services.legacy_dag_node": "services.graph_runner",
        # Reviewed move #2 (m1/56): llm_summarize retired onto the governed
        # gateway — operator-approved migration, predecessor pruned (#56).
        "maistro.capabilities.providers.llm_gateway": "maistro.graph.nodes.llm_summarize",
    }


def test_the_shipped_inventory_matches_the_shipped_code(
    gate, real_repository_ratchet_base: None
) -> None:
    assert gate.main() == 0


def test_the_inventory_records_no_verdicts(gate) -> None:
    """Deciding which callers are legitimate is #56's adjudication; a guess
    recorded here would give that work a false starting point. The metric
    version is provenance, not a verdict: it names the measurement, not the
    judgement."""
    payload = json.loads((ROOT / "quality" / "model-egress.json").read_text())
    assert set(payload) == {"_comment", "modules", "metric_definition_version"}
    assert payload["metric_definition_version"] == gate.METRIC_DEFINITION_VERSION
    assert all(isinstance(module, str) for module in payload["modules"])
