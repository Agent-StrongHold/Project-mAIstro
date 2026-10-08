"""M8-A15 research harness — coverage-guided fuzzing of parser attack surfaces.

Issue #896 (leaf of epic #880, initiative #879). Hypothesis under study:
coverage-guided fuzzing adds value where MAIstro accepts raw or parser-heavy
untrusted inputs, especially when malformed byte/string structure matters more
than semantic state sequences.

This module is a RESEARCH ARTIFACT, not product code. The machinery
(``_fuzzlab.py``) is a deterministic, in-process, PEP 669 coverage-guided
mutational fuzzer — the issue's "Atheris or justified equivalent", justified
in the research note (Atheris needs a libFuzzer-instrumented CPython that this
repo's deterministic CI cannot install or run).

Real MAIstro boundaries probed (both parse raw, host-suppliable bytes):

- ``maistro.extensions.manifest.inspect_manifest`` — the extension manifest
  parser whose docstring contract is to fail closed: the only two outcomes
  are a validated snapshot or a typed ``ManifestRejected``
  (``packages/maistro-core/src/maistro/extensions/manifest.py``). It gates
  what permissions an operator is shown, so any third outcome is a defect.
- ``maistro.agents.store.InMemoryAgentStore.import_gitagent`` — the GitAgent
  zip import boundary (zip container + YAML manifest + UTF-8 payloads →
  ``AgentIdentity``), whose documented rejection type is ``ValueError``
  (``packages/maistro-core/src/maistro/agents/store.py:198``).

The experiment, per the issue: seed with representative valid inputs, fuzz
malformed variants, measure code-path discovery and defects against the
existing Hypothesis baseline (generic binary and JSON-document strategies on
the same targets under the same coverage monitor), plus directed structural
probes to measure what byte-level mutation cannot reach.

Trust boundary: every result here is advisory evidence (see ``_fuzzlab``).
Findings are routed to the owning surfaces in the research note; nothing in
this suite fixes production code or weakens any gate.
"""

from __future__ import annotations

import asyncio
import io
import json
import warnings
import zipfile
from typing import Any

import pytest
import yaml

import maistro.agents.store as agents_store_mod
import maistro.extensions.manifest as manifest_mod
from maistro.agents.base import Agent
from maistro.agents.store import InMemoryAgentStore
from maistro.agents.strategies.direct import DirectStrategy
from maistro.extensions.manifest import inspect_manifest
from maistro.extensions.types import ManifestRejected
from maistro.types.agent import AgentIdentity

from ._fuzzlab import (
    ADVISORY_ONLY,
    RESEARCH_DISPOSITION,
    CampaignResult,
    HypothesisArmResult,
    run_campaign,
    run_hypothesis_arm,
    run_probes,
)

# ---------------------------------------------------------------------------
# Budgets — bounded on purpose: a research campaign is a measured sample, not
# an unbounded soak. Each full campaign costs well under a second in-process.
# ---------------------------------------------------------------------------

MANIFEST_EXECS = 4000
GITAGENT_EXECS = 1500
HYPOTHESIS_EXAMPLES = 250
RNG_SEED = 42

MANIFEST_MOD = manifest_mod
GITAGENT_MOD_OBJ = agents_store_mod

MANIFEST_REJECTIONS: tuple[type[BaseException], ...] = (ManifestRejected,)
GITAGENT_REJECTIONS: tuple[type[BaseException], ...] = (ValueError,)

# ---------------------------------------------------------------------------
# Seed corpora — representative VALID inputs for both boundaries.
# ---------------------------------------------------------------------------


def _manifest_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "manifest_version": 1,
        "id": "acme.chart_tools",
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": "acme",
        "api_version": "1.0.0",
        "permissions": ["network.http", "fs.read"],
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": "a" * 64, "size": 13},
    }
    document.update(overrides)
    return document


def _manifest_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document).encode("utf-8")


MANIFEST_SEEDS: tuple[bytes, ...] = (
    _manifest_bytes(_manifest_document()),
    _manifest_bytes(_manifest_document(dependencies=[{"id": "acme.core", "range": ">=1.0.0"}])),
    _manifest_bytes(_manifest_document(permissions=[])),
)


class _StubLLM:
    pass


class _StubContextBuilder:
    pass


def _seeded_store() -> InMemoryAgentStore:
    """A store with one existing agent, as import_gitagent requires: it clones
    llm/context_builder from the first stored agent (see ``create``)."""
    agent = Agent(
        identity=AgentIdentity(name="base-agent"),
        strategy=DirectStrategy(),
        llm=_StubLLM(),
        context_builder=_StubContextBuilder(),
        prompt_manager=None,
        warden=None,
        session_store=None,
    )
    return InMemoryAgentStore({"base-agent": agent}, prompt_manager=None)


def _gitagent_pack() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("myagent/agent.yaml", yaml.dump({"name": "myagent", "version": "1.0.0"}))
        zf.writestr("myagent/SOUL.md", "soul content here")
        zf.writestr("myagent/RULES.md", "rules content here")
    return buf.getvalue()


GITAGENT_SEEDS: tuple[bytes, ...] = (_gitagent_pack(),)

# ---------------------------------------------------------------------------
# Targets — each raises its documented rejection type(s) or returns.
# ---------------------------------------------------------------------------


def _manifest_target(data: bytes) -> None:
    inspect_manifest(data)


_loop: asyncio.AbstractEventLoop | None = None


def _gitagent_target_bytes(data: bytes) -> str:
    """Import one candidate pack into a throwaway seeded store; returns the
    created agent name on acceptance. zipfile warns (heuristically) about
    overlapping entries in mutated archives; the warning is noise for the
    oracle — the documented rejection contract is ValueError — so it is
    silenced inside the target only."""
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
    store = _seeded_store()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return _loop.run_until_complete(store.import_gitagent(data))


def _gitagent_target(data: bytes) -> None:
    _gitagent_target_bytes(data)


# ---------------------------------------------------------------------------
# Directed structural probes — what byte-level mutation cannot reach.
# ---------------------------------------------------------------------------

_DEEP_ARRAY_JSON = b"[" * 20000
_DEEP_OBJECT_JSON = b'{"a":' * 6000 + b"1" + b"}" * 6000

MANIFEST_PROBES: tuple[tuple[str, bytes], ...] = (
    ("deeply-nested-array-json", _DEEP_ARRAY_JSON),
    ("deeply-nested-object-json", _DEEP_OBJECT_JSON),
)


# ---------------------------------------------------------------------------
# The experiment, frozen.
# ---------------------------------------------------------------------------


def _manifest_campaign() -> CampaignResult:
    return run_campaign(
        _manifest_target,
        module=MANIFEST_MOD,
        seeds=MANIFEST_SEEDS,
        allowed_rejections=MANIFEST_REJECTIONS,
        execs=MANIFEST_EXECS,
        rng_seed=RNG_SEED,
    )


def _gitagent_campaign() -> CampaignResult:
    return run_campaign(
        _gitagent_target,
        module=GITAGENT_MOD_OBJ,
        seeds=GITAGENT_SEEDS,
        allowed_rejections=GITAGENT_REJECTIONS,
        execs=GITAGENT_EXECS,
        rng_seed=RNG_SEED,
    )


def _hypothesis_arms() -> tuple[HypothesisArmResult, HypothesisArmResult, HypothesisArmResult]:
    """The issue's comparison baseline: existing-style Hypothesis strategies on
    the same targets under the same coverage monitor. derandomize pins them."""
    from hypothesis import strategies as st

    binary = st.binary(max_size=2048)
    json_documents = st.recursive(
        st.none() | st.booleans() | st.integers() | st.text(max_size=24),
        lambda inner: (
            st.lists(inner, max_size=6) | st.dictionaries(st.text(max_size=12), inner, max_size=6)
        ),
        max_leaves=40,
    )

    def _json_bytes_strategy() -> Any:
        return json_documents.map(lambda doc: json.dumps(doc).encode("utf-8", "ignore"))

    return (
        run_hypothesis_arm(
            _manifest_target,
            module=MANIFEST_MOD,
            strategy=binary,
            allowed_rejections=MANIFEST_REJECTIONS,
            max_examples=HYPOTHESIS_EXAMPLES,
        ),
        run_hypothesis_arm(
            _manifest_target,
            module=MANIFEST_MOD,
            strategy=_json_bytes_strategy(),
            allowed_rejections=MANIFEST_REJECTIONS,
            max_examples=HYPOTHESIS_EXAMPLES,
        ),
        run_hypothesis_arm(
            _gitagent_target,
            module=GITAGENT_MOD_OBJ,
            strategy=binary,
            allowed_rejections=GITAGENT_REJECTIONS,
            max_examples=HYPOTHESIS_EXAMPLES,
        ),
    )


# ---------------------------------------------------------------------------
# Guards and measurements
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestSeedCorpus:
    def test_manifest_seeds_parse_clean(self) -> None:
        """The corpus is representative valid input: every manifest seed is
        accepted and fully anchored. A rotting seed would silently turn the
        campaign into noise, so it fails here first."""
        for seed in MANIFEST_SEEDS:
            manifest = inspect_manifest(seed)
            assert manifest.source_sha256
            assert manifest.raw == seed

    def test_gitagent_seed_imports_clean(self) -> None:
        """The zip seed round-trips: a real pack the importer accepts."""
        assert _gitagent_target_bytes(GITAGENT_SEEDS[0]) == "myagent"


@pytest.mark.contract("boundary")
@pytest.mark.scope("property")
class TestCampaignMechanics:
    def test_campaigns_reproduce_bit_for_bit_for_a_fixed_seed(self) -> None:
        """Same seed => same corpus growth, edge set, and findings. This is
        the reproducibility evidence the issue asks for, held for both
        targets (smaller budgets than the full campaigns for suite speed)."""
        for target, module, seeds, rejections, execs in (
            (
                _manifest_target,
                MANIFEST_MOD,
                MANIFEST_SEEDS,
                MANIFEST_REJECTIONS,
                1200,
            ),
            (
                _gitagent_target,
                GITAGENT_MOD_OBJ,
                GITAGENT_SEEDS,
                GITAGENT_REJECTIONS,
                800,
            ),
        ):
            first = run_campaign(
                target,
                module=module,
                seeds=seeds,
                allowed_rejections=rejections,
                execs=execs,
                rng_seed=RNG_SEED,
            )
            second = run_campaign(
                target,
                module=module,
                seeds=seeds,
                allowed_rejections=rejections,
                execs=execs,
                rng_seed=RNG_SEED,
            )
            assert first.edges == second.edges
            assert first.corpus_size == second.corpus_size
            assert first.accepted == second.accepted
            assert first.rejected == second.rejected
            assert first.findings == second.findings

    def test_findings_reproduce_their_exception_on_replay(self) -> None:
        """A finding is only evidence if its bytes re-raise its exception."""
        for finding in _gitagent_campaign().findings:
            assert finding.reproduces(_gitagent_target), finding


@pytest.mark.contract("boundary")
@pytest.mark.scope("property")
class TestMeasuredEvidence:
    def test_manifest_campaign_discovers_paths_beyond_seeds_and_hypothesis(self) -> None:
        """Code-path discovery, measured: the coverage-guided campaign must
        reach strictly more manifest-parser edges than its own seed corpus and
        than either Hypothesis arm on the same monitor."""
        campaign = _manifest_campaign()
        hyp_binary, hyp_json, _ = _hypothesis_arms()
        assert campaign.discovered_edges > 0
        assert campaign.corpus_size > len(MANIFEST_SEEDS)
        assert campaign.edges > hyp_binary.edges
        assert campaign.edges > hyp_json.edges

    def test_manifest_boundary_survives_the_byte_campaign(self) -> None:
        """Hardening baseline, pinned: byte-level mutation over valid-manifest
        seeds finds ZERO contract escapes on inspect_manifest. If this ever
        fails, the parser's fail-closed story has regressed and the research
        note's evidence needs revisiting."""
        assert _manifest_campaign().findings == ()

    def test_directed_probes_escape_the_fail_closed_contract(self) -> None:
        """The routed defect (#896 routing): deeply nested JSON makes
        inspect_manifest raise RecursionError — a third outcome its fail-closed
        contract does not admit (manifest.py:147 catches UnicodeDecodeError and
        JSONDecodeError only). Byte-level mutation cannot build this input;
        structure-aware generation can. Recorded as evidence, routed to the
        extensions manifest surface; not fixed in this research lane."""
        probes = run_probes(_manifest_target, MANIFEST_PROBES, MANIFEST_REJECTIONS)
        assert {finding.exception_type for finding in probes} == {"RecursionError"}
        for finding in probes:
            assert finding.reproduces(_manifest_target)

    def test_gitagent_campaign_escapes_the_rejection_contract(self) -> None:
        """The routed defect (#896 routing): import_gitagent documents
        ValueError as its rejection type (its unit suite pins exactly that),
        but host-mutable container bytes escape as zipfile/yaml machinery
        errors — BadZipFile from truncation/corruption, NotImplementedError
        from unsupported compression bytes (store.py:201/215). The campaign
        finds these within its first execs; every escape type is outside the
        documented contract."""
        campaign = _gitagent_campaign()
        assert campaign.findings, "expected contract escapes on the zip boundary"
        types = set(campaign.finding_type_counts)
        assert "BadZipFile" in types
        assert types <= {"BadZipFile", "NotImplementedError", "RuntimeError", "ParserError"}
        assert not types & {"ValueError", "ManifestRejected"}
        for finding in campaign.findings:
            assert finding.reproduces(_gitagent_target)

    def test_hypothesis_arms_measured_on_the_same_targets(self) -> None:
        """The comparison baseline is recorded, not assumed: generic Hypothesis
        strategies reject-but-don't-crash the manifest parser (no escapes in
        the pinned classes) and escape the zip boundary only via BadZipFile —
        the campaign's seeded, coverage-guided loop dominates both on path
        discovery (asserted in the manifest test above)."""
        hyp_manifest_binary, hyp_manifest_json, hyp_gitagent = _hypothesis_arms()
        assert hyp_manifest_binary.execs == HYPOTHESIS_EXAMPLES
        assert hyp_manifest_json.execs == HYPOTHESIS_EXAMPLES
        assert hyp_manifest_binary.edges > 0
        assert set(hyp_manifest_binary.finding_type_counts) <= {"RecursionError"}
        assert set(hyp_manifest_json.finding_type_counts) <= {"RecursionError"}
        assert hyp_gitagent.execs == HYPOTHESIS_EXAMPLES
        assert "BadZipFile" in set(hyp_gitagent.finding_type_counts)


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestResearchContract:
    def test_experiment_is_advisory_and_incubate(self) -> None:
        """The evidence-only marker and the terminal disposition are set and
        cannot rot silently."""
        assert ADVISORY_ONLY is True
        assert RESEARCH_DISPOSITION == "INCUBATE"

    def test_results_are_frozen_records(self) -> None:
        """Campaign/arm results are frozen dataclasses: evidence cannot be
        mutated into a different verdict after the fact."""
        import dataclasses

        result = _manifest_campaign()
        for frozen in (result, *result.findings):
            with pytest.raises(dataclasses.FrozenInstanceError):
                frozen.execs = -1  # type: ignore[misc]

    def test_research_machinery_is_inert_to_production_source(self) -> None:
        """AST source scan: no packages/*/src module imports this lab. The
        fuzzer cannot ship enabled because it cannot ship at all (M8-A3's
        machinery-inert guard, applied to this lab)."""
        import ast
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[4]
        offenders: list[str] = []
        for path in (repo_root / "packages").glob("*/src/**/*.py"):
            tree = ast.parse(path.read_bytes())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "fuzzlab" in alias.name:
                            offenders.append(f"{path}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module and "fuzzlab" in node.module:
                    offenders.append(f"{path}: from {node.module}")
        assert offenders == []
