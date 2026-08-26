"""Tests for the frontend-to-backend route gate (#295).

The gate exists because a 404 is not self-announcing on this seam. `fetch`
rejects on network failure, not on an error status, so a control wired to a
route nobody registered renders, responds to clicks, and reports a state that
never happened. Tools Lab did that for four tools across three endpoints and no
test failed.

Two failure directions organise the cases below, as with every gate here. A
matcher that stops recognising an unregistered path lets the class back in. One
that flags a legitimate idiom -- and this frontend uses several -- gets waived
everywhere within a week and then deleted.

The route table is not mocked in the repository cases: building the real app is
what makes this a check about the shipped surface rather than about two lists
someone maintained by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-frontend-api-routes.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_frontend_api_routes", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call(check, path: str):
    _, prefix_only = check.parse(path)
    return check.Call("f.tsx", 1, path, prefix_only=prefix_only)


class TestTheDefectItWasWrittenFor:
    @pytest.mark.parametrize(
        "path",
        [
            "/v1/tools-lab/status",
            "/v1/tools-lab/${id}/start",
            "/v1/tools-lab/${id}/stop",
        ],
    )
    def test_the_three_tools_lab_calls_match_nothing(self, check, path):
        """Verified against the real pre-fix page: all three reported."""
        routes = ["/v1/agents", "/v1/containers/{container_id}/start", "/v1/tasks"]
        assert not any(check.matches(_call(check, path), r) for r in routes)

    def test_a_path_whose_first_segment_is_unregistered_cannot_be_saved_by_a_tail(self, check):
        """`/v1/tools-lab` was the prefix of no registered route, so no unknown
        tail could have made those calls resolve. That is what makes the weaker
        prefix claim sufficient for this defect."""
        assert not any(
            check.matches(_call(check, "/v1/tools-lab${anything}"), r)
            for r in ["/v1/tools/{id}", "/v1/lab"]
        )


class TestWhatMustNotBeFlagged:
    """Each false positive here is a waiver someone adds, and a gate that is
    mostly waivers stops being read."""

    def test_an_interpolated_id_matches_a_named_route_param(self, check):
        assert check.matches(_call(check, "/v1/dags/${id}/nodes"), "/v1/dags/{dag_id}/nodes")

    def test_a_literal_matches_a_named_route_param(self, check):
        """The frontend often hardcodes a known id. The route still serves it."""
        assert check.matches(_call(check, "/v1/agents/researcher"), "/v1/agents/{agent_id}")

    def test_a_query_string_interpolation_is_not_a_path_segment(self, check):
        """`/v1/audit${qs ? `?${qs}` : ""}` requests `/v1/audit`. Treating the
        interpolation as a segment invents one that is never requested -- and
        the nested backtick means it cannot be parsed as an id either."""
        call = _call(check, "/v1/audit${qs ? `?${qs}")
        assert call.prefix_only
        assert check.matches(call, "/v1/audit")

    def test_segment_counts_must_agree_when_the_path_is_complete(self, check):
        """Without this, every call matches its own prefix and the gate passes
        everything."""
        assert not check.matches(_call(check, "/v1/agents/x/y"), "/v1/agents/{id}")
        assert not check.matches(_call(check, "/v1/agents"), "/v1/agents/{id}")

    def test_a_prefix_claim_still_requires_the_known_segments_to_match(self, check):
        """The weaker claim is weaker, not absent."""
        call = _call(check, '/v1/nope${qs ? `?a` : ""}')
        assert call.prefix_only
        assert not check.matches(call, "/v1/agents/forge")

    def test_a_well_formed_interpolation_is_a_segment_not_a_downgrade(self, check):
        """`${id}` names one segment, so the path stays a complete claim and
        the segment count still has to agree."""
        call = _call(check, "/v1/agents/${id}")
        assert not call.prefix_only
        assert check.matches(call, "/v1/agents/{agent_id}")
        assert not check.matches(call, "/v1/agents/{agent_id}/scan")


class TestBaseConstants:
    """`const API = "/v1/evolution"` composed as `${API}/status`. Left
    unresolved this is wrong twice: the base reports as unregistered (nothing
    is mounted at `/v1/evolution` itself) and the eight real calls built from
    it stay invisible."""

    def test_a_base_binding_is_resolved_into_its_calls(self, check, tmp_path):
        f = tmp_path / "Evolution.tsx"
        f.write_text(
            'const API = "/v1/evolution";\n'
            "async function load() {\n"
            "  await fetch(`${API}/status`);\n"
            "  await fetch(`${API}/population`);\n"
            "}\n",
            encoding="utf-8",
        )
        paths = [c.path for c in check.calls_in(f, repo_root=tmp_path)]
        assert paths == ["/v1/evolution/status", "/v1/evolution/population"]

    def test_the_binding_line_itself_is_not_a_call(self, check, tmp_path):
        """It is a value, not a request. Reporting it as unregistered is the
        false positive that made this resolution necessary."""
        f = tmp_path / "RSI.tsx"
        f.write_text('const API = "/v1/rsi";\n', encoding="utf-8")
        assert check.calls_in(f, repo_root=tmp_path) == []

    def test_an_unknown_base_is_skipped_rather_than_guessed(self, check, tmp_path):
        f = tmp_path / "X.tsx"
        f.write_text("await fetch(`${SOMETHING_ELSE}/status`);\n", encoding="utf-8")
        assert check.calls_in(f, repo_root=tmp_path) == []


class TestTheEscapeHatch:
    def test_a_waiver_suppresses_on_the_same_line(self, check, tmp_path):
        f = tmp_path / "X.tsx"
        f.write_text(
            'fetch("/v1/sidecar/thing");  // frontend-api-routes: allow served by the sidecar\n',
            encoding="utf-8",
        )
        assert check.calls_in(f, repo_root=tmp_path) == []

    def test_a_waiver_suppresses_from_the_line_above(self, check, tmp_path):
        f = tmp_path / "X.tsx"
        f.write_text(
            "// frontend-api-routes: allow served by the sidecar, see #295\n"
            'fetch("/v1/sidecar/thing");\n',
            encoding="utf-8",
        )
        assert check.calls_in(f, repo_root=tmp_path) == []

    def test_a_waiver_without_a_reason_does_not_suppress(self, check, tmp_path):
        """The reason is the whole mechanism. A bare marker reads as review in
        the diff while recording nothing."""
        f = tmp_path / "X.tsx"
        f.write_text(
            'fetch("/v1/sidecar/thing");  // frontend-api-routes: allow\n', encoding="utf-8"
        )
        assert [c.path for c in check.calls_in(f, repo_root=tmp_path)] == ["/v1/sidecar/thing"]


class TestItRefusesToGuess:
    """Reporting green because it could not tell is the one outcome that would
    make this gate actively harmful."""

    def test_an_optional_router_that_failed_to_load_fails_the_gate(
        self, check, monkeypatch, capsys
    ):
        """Four routers are mounted inside a `try`. Checked against a table
        missing one, every call into it reports as unregistered and the real
        cause is an import error one layer down -- so the gate declines to
        answer instead of answering wrongly."""
        monkeypatch.setattr(
            check,
            "registered_routes",
            lambda: ({}, ["routes.design: ModuleNotFoundError: maistro_design"]),
        )
        assert check.main() == 1
        out = capsys.readouterr().out
        assert "route table is incomplete" in out
        assert "maistro_design" in out

    def test_an_empty_route_table_is_a_failure(self, check, monkeypatch, capsys):
        monkeypatch.setattr(check, "registered_routes", lambda: ({}, []))
        assert check.main() == 1
        assert "no routes at all" in capsys.readouterr().out

    def test_finding_no_call_sites_is_a_failure(self, check, monkeypatch, capsys):
        """An empty scan reporting "ok: 0 call sites" is the same false green
        as a gate that never ran."""
        monkeypatch.setattr(
            check, "registered_routes", lambda: ({"/v1/agents": frozenset({"GET"})}, [])
        )
        monkeypatch.setattr(check, "calls_in", lambda _path, _root=None: [])
        assert check.main() == 1
        assert "nothing was measured" in capsys.readouterr().out

    def test_finding_no_frontend_files_is_a_failure(self, check, monkeypatch, capsys):
        monkeypatch.setattr(
            check, "registered_routes", lambda: ({"/v1/agents": frozenset({"GET"})}, [])
        )
        monkeypatch.setattr(check, "frontend_files", list)
        assert check.main() == 1
        assert "no frontend sources" in capsys.readouterr().out


class TestTheRepository:
    """Against the real app and the real frontend. If these fail, a control in
    the shipped UI reaches a route nobody registered."""

    @pytest.mark.timeout(300)
    def test_every_frontend_call_resolves(self, check):
        routes, degraded = check.registered_routes()
        assert degraded == [], f"optional router(s) did not load: {degraded}"
        calls = [c for p in check.frontend_files() for c in check.calls_in(p)]
        unresolved = [
            c
            for c in calls
            if not any(check.matches(c, path, verbs) for path, verbs in routes.items())
        ]
        assert unresolved == [], "\n".join(check.Finding(c).render() for c in unresolved)

    @pytest.mark.timeout(300)
    def test_it_is_actually_measuring_something(self, check):
        """A gate whose scan silently shrank would report a clean tree by
        checking almost nothing."""
        routes, _ = check.registered_routes()
        calls = [c for p in check.frontend_files() for c in check.calls_in(p)]
        assert len(routes) > 100
        assert len(calls) > 100

    @pytest.mark.timeout(300)
    def test_no_tools_lab_route_is_registered(self, check):
        """The other half of #295: the facade is gone, and nothing quietly
        added the backend for it either."""
        routes, _ = check.registered_routes()
        assert [r for r in routes if "tools-lab" in r] == []


class TestTheReport:
    """A gate is read by someone deciding whether to trust a merge, so what it
    prints is part of what it does. A gate that says only "no" gets worked
    around rather than followed."""

    def _one_finding(self, check, monkeypatch, path: str = "/v1/tools-lab/status"):
        monkeypatch.setattr(
            check, "registered_routes", lambda: ({"/v1/agents": frozenset({"GET"})}, [])
        )
        monkeypatch.setattr(check, "frontend_files", lambda: [Path("ToolsLab.tsx")])
        monkeypatch.setattr(
            check,
            "calls_in",
            lambda _p, _root=None: [check.Call("pages/ToolsLab.tsx", 19, path)],
        )

    def test_an_unresolved_call_fails_and_names_it(self, check, monkeypatch, capsys):
        self._one_finding(check, monkeypatch)
        assert check.main() == 1
        out = capsys.readouterr().out
        assert "reach no registered backend route" in out
        assert "pages/ToolsLab.tsx:19" in out
        assert "/v1/tools-lab/status" in out

    def test_it_explains_why_a_404_is_not_self_announcing(self, check, monkeypatch, capsys):
        """The reason someone needs, not just the fact. Without it the obvious
        reading is "the backend is down"."""
        self._one_finding(check, monkeypatch)
        check.main()
        out = capsys.readouterr().out
        assert "does not reject on a 404" in out
        assert "frontend-api-routes: allow <reason>" in out

    def test_the_same_call_is_listed_once(self, check, monkeypatch, capsys):
        """Two routes are checked against, so a finding is generated per
        non-match. Printing the same line twice reads as two defects."""
        monkeypatch.setattr(
            check,
            "registered_routes",
            lambda: ({"/v1/a": frozenset({"GET"}), "/v1/b": frozenset({"GET"})}, []),
        )
        monkeypatch.setattr(check, "frontend_files", lambda: [Path("X.tsx")])
        monkeypatch.setattr(
            check, "calls_in", lambda _p, _root=None: [check.Call("X.tsx", 3, "/v1/nope")] * 2
        )
        assert check.main() == 1
        out = capsys.readouterr().out
        assert out.count("X.tsx:3") == 1
        assert "1 frontend call(s)" in out

    def test_a_prefix_claim_is_marked_as_one_in_the_report(self, check):
        """So a reader is not left thinking the full path was checked."""
        call = check.Call("X.tsx", 1, "/v1/nope${tail}", prefix_only=True)
        assert "(as a prefix)" in check.Finding(call).render()

    def test_a_complete_claim_is_not_marked(self, check):
        call = check.Call("X.tsx", 1, "/v1/nope", prefix_only=False)
        assert "(as a prefix)" not in check.Finding(call).render()

    def test_a_clean_run_says_how_much_it_checked(self, check, monkeypatch, capsys):
        """ "ok" alone is indistinguishable from a scan that found nothing to
        do, which is the state every other refusal here exists to prevent."""
        monkeypatch.setattr(
            check, "registered_routes", lambda: ({"/v1/agents": frozenset({"GET"})}, [])
        )
        monkeypatch.setattr(check, "frontend_files", lambda: [Path("X.tsx")])
        monkeypatch.setattr(
            check, "calls_in", lambda _p, _root=None: [check.Call("X.tsx", 1, "/v1/agents")]
        )
        assert check.main() == 0
        out = capsys.readouterr().out
        assert "1 frontend call site(s)" in out
        assert "1 registered route(s)" in out


class TestTheImportPaths:
    """What the app needs on `sys.path`. Wrong, and the optional routers fail
    to import, and the gate refuses to answer -- which is what happened to the
    first version run as a bare CI step."""

    def test_it_mirrors_the_repository_layout(self, check):
        names = {p.parent.name for p in check.import_paths() if p.name == "src"}
        assert {"maistro-core", "maistro-design", "maistro-canvas"} <= names

    def test_the_backend_is_last_so_it_lands_first_on_the_path(self, check):
        """The monorepo root also has a `services/` package that shadows the
        app's own when it wins the race -- the same hazard the Conductor's own
        conftest guards against."""
        assert check.import_paths()[-1] == check.BACKEND


class TestTheVerbIsCheckedToo:
    """A path match alone accepts a GET against a POST-only route: Starlette
    answers 405 and the control is exactly as broken as if nothing were
    registered (#295 review).

    This is not theoretical here. It is what exposed `apiPost("/v1/agents/scan")`
    — a live Builder button posting to a path that does not exist, which the
    path-only matcher accepted against `GET /v1/agents/{agent_id}` because a
    route parameter swallows any single segment. Filed as #418."""

    def test_a_get_against_a_post_only_route_is_a_finding(self, check):
        call = check.Call("X.tsx", 1, "/v1/chat/complete", method="GET")
        assert not check.matches(call, "/v1/chat/complete", frozenset({"POST"}))

    def test_the_matching_verb_resolves(self, check):
        call = check.Call("X.tsx", 1, "/v1/chat/complete", method="POST")
        assert check.matches(call, "/v1/chat/complete", frozenset({"POST"}))

    def test_an_unread_verb_checks_no_verb(self, check):
        """None means "could not tell", and a wrong verb here is a false
        finding. Unreadable must not become a guess."""
        call = check.Call("X.tsx", 1, "/v1/chat/complete", method=None)
        assert check.matches(call, "/v1/chat/complete", frozenset({"POST"}))

    def test_a_prefix_claim_does_not_check_the_verb(self, check):
        """The route it will actually reach is unknown, so the verb of a route
        it merely shares a prefix with says nothing."""
        call = check.Call("X.tsx", 1, "/v1/chat${x}", method="GET", prefix_only=True)
        assert check.matches(call, "/v1/chat/complete", frozenset({"POST"}))

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ('await apiPost("/v1/x", body);', "POST"),
            ('await apiGet<T>("/v1/x");', "GET"),
            ('await apiDelete("/v1/x");', "DELETE"),
            ('await apiPut("/v1/x", b);', "PUT"),
            ('await apiPatch("/v1/x", b);', "PATCH"),
            ('await fetch("/v1/x");', "GET"),
            ('const u = "/v1/x";', None),
        ],
    )
    def test_the_verb_is_read_from_the_call_site(self, check, line, expected):
        assert check.method_of([line], 0) == expected

    def test_an_explicit_method_option_wins_over_the_helper(self, check):
        """`apiPost` is not used with an overriding option today, but if it ever
        is, the option is what the browser sends."""
        assert check.method_of(['apiPost("/v1/x", { method: "PUT" });'], 0) == "PUT"

    def test_a_method_on_a_following_line_is_found(self, check):
        """`fetch(url, {` routinely puts `method:` on the next line."""
        lines = ['await fetch("/v1/x", {', '  method: "DELETE",', "});"]
        assert check.method_of(lines, 0) == "DELETE"

    def test_the_repository_route_table_carries_verbs(self, check):
        routes, _ = check.registered_routes()
        assert routes["/v1/chat/complete"] == frozenset({"POST"})


class TestAnInterpolationGluedToASegmentIsASuffix:
    """#295 review. The first version turned every well-formed interpolation
    into a path segment, including one adjacent to the segment before it.

    Measured on the real frontend: `/v1/optimizer/proposals${query}`, where
    `query` is `""` or `"?decision=..."`, became `/v1/optimizer/proposals/*` —
    which matched `/v1/optimizer/{dag_id}/proposals` and
    `/v1/optimizer/{dag_id}/run`, neither of them the route being called, and
    did **not** match the real `/v1/optimizer/proposals`. Deleting that route
    would have left the gate green."""

    def test_a_glued_interpolation_truncates_and_downgrades(self, check):
        segments, prefix_only = check.parse("/v1/optimizer/proposals${query}")
        assert segments == ["v1", "optimizer", "proposals"]
        assert prefix_only

    def test_a_whole_segment_interpolation_stays_a_segment(self, check):
        """The other half: `${id}` between slashes is an id, not a suffix."""
        segments, prefix_only = check.parse("/v1/dags/${id}/nodes")
        assert segments == ["v1", "dags", check.WILDCARD, "nodes"]
        assert not prefix_only

    def test_a_trailing_whole_segment_interpolation_stays_a_segment(self, check):
        segments, prefix_only = check.parse("/v1/agents/${id}")
        assert segments == ["v1", "agents", check.WILDCARD]
        assert not prefix_only

    def test_the_real_optimizer_call_now_reaches_its_own_route(self, check):
        routes, _ = check.registered_routes()
        call = check.Call("X.tsx", 63, "/v1/optimizer/proposals${query}", method="GET")
        call = check.Call(
            "X.tsx", 63, "/v1/optimizer/proposals${query}", method="GET", prefix_only=True
        )
        assert check.matches(call, "/v1/optimizer/proposals", routes["/v1/optimizer/proposals"])


class TestABaseHandedOverWhole:
    """#295 review. Binding lines are skipped as "not a call" and only template
    uses were resolved, so `const API = "/v1/missing"; fetch(API)` produced no
    Call at all — an unregistered base passing as long as the file contained
    some other measured call."""

    def test_a_base_passed_directly_to_fetch_is_a_call(self, check, tmp_path):
        f = tmp_path / "X.tsx"
        f.write_text('const API = "/v1/missing";\nawait fetch(API);\n', encoding="utf-8")
        calls = check.calls_in(f, repo_root=tmp_path)
        assert [c.path for c in calls] == ["/v1/missing"]

    def test_a_base_passed_directly_to_a_helper_is_a_call(self, check, tmp_path):
        f = tmp_path / "X.tsx"
        f.write_text('const API = "/v1/missing";\nawait apiPost(API, body);\n', encoding="utf-8")
        calls = check.calls_in(f, repo_root=tmp_path)
        assert [(c.path, c.method) for c in calls] == [("/v1/missing", "POST")]

    def test_composition_still_works_alongside_it(self, check, tmp_path):
        f = tmp_path / "X.tsx"
        f.write_text(
            'const API = "/v1/evolution";\nawait fetch(`${API}/status`);\nawait fetch(API);\n',
            encoding="utf-8",
        )
        assert [c.path for c in check.calls_in(f, repo_root=tmp_path)] == [
            "/v1/evolution/status",
            "/v1/evolution",
        ]

    def test_an_unknown_identifier_is_not_invented(self, check, tmp_path):
        f = tmp_path / "X.tsx"
        f.write_text("await fetch(SOMETHING_ELSE);\n", encoding="utf-8")
        assert check.calls_in(f, repo_root=tmp_path) == []


class TestTheFeatureInventory:
    """#295 review. The route and page were removed while `README.md` still
    listed Tools Lab as a shipped surface with Launch/Stop buttons — telling a
    reader a feature exists when neither its navigation entry nor its route
    does."""

    def test_the_readme_no_longer_lists_tools_lab(self):
        assert "Tools Lab" not in (ROOT / "README.md").read_text(encoding="utf-8")
