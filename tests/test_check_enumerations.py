"""The enumeration ratchet must fail on a gap, and on a stale baseline entry.

scripts/check_enumerations.py exists because four reviews in a row found a
hand-written security enumeration that had stopped covering its own subject. A
checker for that failure mode is worthless if it silently passes, so the checker
gets the same treatment it imposes: tests that assert it fires, not just that it
runs.

The two directions matter equally. Failing on a *new* gap is the obvious half.
Failing on a *fixed* gap still listed in the baseline is what stops the baseline
from becoming the permanent allowlist that every previous control decayed into.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_enumerations.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_check_enumerations", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations through sys.modules[cls.__module__], so the
    # module has to be registered before exec_module or Gap's creation raises.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    yield mod
    del sys.modules[spec.name]


def _run(module, monkeypatch, gaps, baseline):
    """Drive main() with a synthetic gap set and baseline, and return its exit code."""
    monkeypatch.setattr(module, "CHECKS", {"synthetic": lambda: (gaps, None)})
    monkeypatch.setattr(module, "load_baseline", lambda: baseline)
    monkeypatch.setattr("sys.argv", ["check_enumerations.py"])
    return module.main()


def test_clean_tree_passes(module, monkeypatch):
    assert _run(module, monkeypatch, gaps=[], baseline={}) == 0


def test_new_gap_fails(module, monkeypatch):
    gap = module.Gap("synthetic", "POST /v1/danger", "no scope entry")
    assert _run(module, monkeypatch, gaps=[gap], baseline={}) == 1


def test_baselined_gap_is_tolerated(module, monkeypatch):
    gap = module.Gap("synthetic", "POST /v1/danger", "no scope entry")
    baseline = {gap.key(): gap.detail}
    assert _run(module, monkeypatch, gaps=[gap], baseline=baseline) == 0


def test_stale_baseline_entry_fails(module, monkeypatch):
    """A gap that has been fixed must not stay in the baseline.

    Without this the file accumulates entries for controls that are already
    correct, and it becomes impossible to tell tolerated debt from stale noise —
    which is precisely how an allowlist stops meaning anything.
    """
    baseline = {"synthetic::POST /v1/fixed": "no scope entry"}
    assert _run(module, monkeypatch, gaps=[], baseline=baseline) == 1


def test_check_that_cannot_run_is_a_failure_not_a_skip(module, monkeypatch):
    """An unavailable check must never read as a pass.

    The routes check needs to import the real FastAPI app. If that import breaks,
    the honest outcome is a red build: a checker that quietly reports success
    when it checked nothing is worse than no checker, because it also removes
    the pressure to notice.
    """
    monkeypatch.setattr(module, "CHECKS", {"synthetic": lambda: ([], "deps missing")})
    monkeypatch.setattr(module, "load_baseline", dict)
    monkeypatch.setattr("sys.argv", ["check_enumerations.py"])
    assert module.main() == 1


def test_committed_baseline_is_well_formed(module):
    """Every tolerated entry needs a check name the script actually runs."""
    data = json.loads(module.BASELINE_PATH.read_text(encoding="utf-8"))
    tolerated = data["tolerated"]
    assert tolerated, "an empty baseline should be deleted, not committed"
    known = set(module.CHECKS)
    for key in tolerated:
        check = key.split("::", 1)[0]
        assert check in known, f"baseline entry {key!r} names unknown check {check!r}"


class TestInvokeSuffixCarveOutRemoved:
    """#403: ``_route_is_scoped`` no longer blesses a path for ending in
    "/invoke". The old shortcut mirrored the middleware carve-out it modeled
    and inherited its flaw: any future route choosing the suffix skipped
    classification — an unclassified mutation waved through by URL naming.
    A route is now scoped only through a registered capability prefix or an
    explicit ROUTE_EXEMPT entry with a named reason."""

    def test_unclassified_future_invoke_route_is_a_gap(self, module):
        """An .../invoke route with no policy resolution is NOT scoped —
        check A reports it and the build fails."""
        protected = {"POST": {"/v1/agents": "agents.write"}}
        assert not module._route_is_scoped("/v1/future-thing/invoke", "POST", protected)

    def test_invoke_route_scopes_only_through_registered_capability(self, module):
        """The same route IS scoped when its prefix carries a registered
        capability — the identifier binds, the suffix is irrelevant."""
        protected = {"POST": {"/v1/agents": "agents.write"}}
        assert module._route_is_scoped("/v1/agents/x/invoke", "POST", protected)

    def test_invoke_route_unscoped_only_via_explicit_reviewed_exemption(self, module):
        """The one legitimate way a future .../invoke route skips a scope
        entry is a documented ROUTE_EXEMPT decision, same as any other
        route — /v1/chat is exempt-by-declaration, /v1/containers is not."""
        assert module._route_is_scoped("/v1/chat/foo/invoke", "POST", {})
        assert not module._route_is_scoped("/v1/containers/x/invoke", "POST", {})
