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
    spec = importlib.util.spec_from_file_location("check_model_egress", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- detection ----------------------------------------------------------------


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
    assert gate.CANDIDATE_MIGRATIONS == {"services.legacy_dag_node": "services.graph_runner"}


def test_the_shipped_inventory_matches_the_shipped_code(gate) -> None:
    assert gate.main() == 0


def test_the_inventory_records_no_verdicts(gate) -> None:
    """Deciding which callers are legitimate is #56's adjudication; a guess
    recorded here would give that work a false starting point."""
    payload = json.loads((ROOT / "quality" / "model-egress.json").read_text())
    assert set(payload) == {"_comment", "modules"}
    assert all(isinstance(module, str) for module in payload["modules"])
