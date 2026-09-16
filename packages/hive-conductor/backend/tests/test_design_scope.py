"""The design routes carry the caller's scope into the store (#326).

`GET /v1/design/projects/{id}` and the render route took no scope at all, so an
authenticated caller could read or render any org's project. The store enforces
scope now (`packages/maistro-design/tests/test_project_scope.py` holds that
half); these are the route's own end of it — that the resolved scope actually
reaches the store, and that resolving it is not something a blank value can
slip past.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, ClassVar

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException  # noqa: E402
from routes import design as design_routes  # noqa: E402

from maistro_design.types import (  # noqa: E402
    ArtifactKind,
    ArtifactNode,
    DesignOutput,
    OutputFormat,
)

pytestmark = [pytest.mark.contract("boundary")]


class _State:
    """A request's `state`. Attributes are set per test, never defaulted."""


class _Request:
    def __init__(self, **attrs: Any) -> None:
        self.state = _State()
        for name, value in attrs.items():
            setattr(self.state, name, value)


class _Store:
    """Records the scope each call was given, and answers nothing."""

    def __init__(self, project: Any = None) -> None:
        self.project = project
        self.calls: list[dict[str, Any]] = []

    async def get(self, project_id: str, *, org_id: str) -> Any:
        self.calls.append({"project_id": project_id, "org_id": org_id})
        return self.project


@pytest.fixture()
def ready(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Status:
        ready = True
        cause = ""

    monkeypatch.setattr(design_routes, "get_design_status", lambda: _Status())


class TestResolvingTheScope:
    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    def test_no_scope_at_all_falls_back_to_the_deployments(self) -> None:
        """The Agent Conductor is single-org by construction, so one
        deployment-wide scope is the truth when nothing else says otherwise."""
        assert design_routes._get_org_id(_Request()) == design_routes.CONDUCTOR_ORG_ID

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    def test_a_scope_the_deployment_set_wins(self) -> None:
        assert design_routes._get_org_id(_Request(org_id="org-7")) == "org-7"

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    @pytest.mark.parametrize("blank", ["", None])
    def test_a_present_but_blank_scope_is_refused(self, blank: Any) -> None:
        """`or CONDUCTOR_ORG_ID` mapped this to the default scope, so a
        middleware setting it to mean "unresolved" or "unauthorized" was handed
        read and write access to the deployment's own projects (Codex, #326).
        Absent and empty are different answers."""
        with pytest.raises(HTTPException) as raised:
            design_routes._get_org_id(_Request(org_id=blank))
        assert raised.value.status_code == 403


class TestTheRoutesPassItDown:
    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_fetching_a_project_carries_the_scope(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Project:
            outputs: ClassVar[list[Any]] = []

            @staticmethod
            def to_dict() -> dict[str, Any]:
                return {"id": "p-1"}

        store = _Store(project=_Project())
        monkeypatch.setattr(design_routes, "get_design_store", lambda: store)
        await design_routes.get_design_project("p-1", _Request(org_id="org-7"))
        assert store.calls == [{"project_id": "p-1", "org_id": "org-7"}]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_fetching_a_persisted_output_returns_its_content_and_provenance(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = DesignOutput(
            root=ArtifactNode(
                key="prompt-stack",
                kind=ArtifactKind.FILE,
                format=OutputFormat.MARKDOWN,
                value="prepared prompt",
            ),
            metadata={"production_stage": "prompt_preparation", "visual_generation": False},
            run_id="run-1",
            node_run_id="node-1",
            attempt_id="attempt-1",
        )

        class _Project:
            outputs: ClassVar[list[DesignOutput]] = [output]

            @staticmethod
            def to_dict() -> dict[str, Any]:
                return {"id": "p-1"}

        store = _Store(project=_Project())
        monkeypatch.setattr(design_routes, "get_design_store", lambda: store)
        answer = await design_routes.get_design_project("p-1", _Request(org_id="org-7"))

        assert answer["outputs"] == [
            {
                "format": "markdown",
                "content": "prepared prompt",
                "url": None,
                "trust_tier": "t3",
                "metadata": {"production_stage": "prompt_preparation", "visual_generation": False},
                "artifact_kind": "file",
                "run_id": "run-1",
                "node_run_id": "node-1",
                "attempt_id": "attempt-1",
            }
        ]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-3")
    async def test_a_project_outside_the_scope_is_a_404_not_a_403(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absence, not refusal: whether a project with that id exists in
        another scope is itself scoped information."""
        store = _Store(project=None)
        monkeypatch.setattr(design_routes, "get_design_store", lambda: store)
        with pytest.raises(HTTPException) as raised:
            await design_routes.get_design_project("p-1", _Request(org_id="org-7"))
        assert raised.value.status_code == 404

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_an_unconfigured_store_is_a_503_not_an_empty_project(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(design_routes, "get_design_store", lambda: None)
        with pytest.raises(HTTPException) as raised:
            await design_routes.get_design_project("p-1", _Request())
        assert raised.value.status_code == 503

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_listing_without_persistence_is_a_503_not_an_empty_project(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(design_routes, "get_design_store", lambda: None)
        with pytest.raises(HTTPException) as raised:
            await design_routes.list_design_projects(_Request())
        assert raised.value.status_code == 503
        assert "persistence unavailable" in str(raised.value.detail).lower()

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_listing_with_an_uninitialized_store_is_a_503_not_a_500(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing_store() -> Any:
            raise RuntimeError("DesignProjectStore not initialized")

        monkeypatch.setattr(design_routes, "get_design_store", missing_store)
        with pytest.raises(HTTPException) as raised:
            await design_routes.list_design_projects(_Request())
        assert raised.value.status_code == 503
        assert "not initialized" in str(raised.value.detail)

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_rendering_without_persistence_is_a_503_not_a_500(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(design_routes, "get_design_store", lambda: None)
        with pytest.raises(HTTPException) as raised:
            await design_routes.create_render_job("p-1", _Request())
        assert raised.value.status_code == 503
        assert "persistence unavailable" in str(raised.value.detail).lower()

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_rendering_a_project_carries_the_scope(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rendering must not disclose a project outside the caller's scope."""
        store = _Store(project=None)
        monkeypatch.setattr(design_routes, "get_design_store", lambda: store)
        with pytest.raises(HTTPException) as raised:
            await design_routes.create_render_job("p-1", _Request(org_id="org-7"))
        assert raised.value.status_code == 404
        assert store.calls == [{"project_id": "p-1", "org_id": "org-7"}]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_rendering_an_in_scope_project_is_disabled_until_canvas_is_connected(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _Store(project=object())
        monkeypatch.setattr(design_routes, "get_design_store", lambda: store)
        with pytest.raises(HTTPException) as raised:
            await design_routes.create_render_job("p-1", _Request(org_id="org-7"))
        assert raised.value.status_code == 501
        assert "canonical Canvas rendering seam" in str(raised.value.detail)
        assert store.calls == [{"project_id": "p-1", "org_id": "org-7"}]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_polling_a_render_job_is_disabled_until_canvas_is_connected(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _Store(project=object())
        monkeypatch.setattr(design_routes, "get_design_store", lambda: store)
        with pytest.raises(HTTPException) as raised:
            await design_routes.get_render_job_status("p-1", "job-1", _Request(org_id="org-7"))
        assert raised.value.status_code == 501
        assert "canonical Canvas rendering seam" in str(raised.value.detail)
        assert store.calls == [{"project_id": "p-1", "org_id": "org-7"}]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-2")
    async def test_listing_projects_uses_the_resolved_scope(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        class _ListStore:
            @staticmethod
            async def list_by_org(org_id: str) -> list[Any]:
                seen.append(org_id)
                return []

            @staticmethod
            async def list_by_skill(skill_slug: str, org_id: str) -> list[Any]:
                seen.append(org_id)
                return []

        monkeypatch.setattr(design_routes, "get_design_store", lambda: _ListStore())
        await design_routes.list_design_projects(_Request(org_id="org-7"))
        await design_routes.list_design_projects(_Request(org_id="org-7"), skill_slug="login-flow")
        assert seen == ["org-7", "org-7"]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-2")
    async def test_creating_a_project_stamps_the_resolved_scope_on_it(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The write end. The store refuses a scope-less project, so the scope
        the route resolved has to be the one the engine is told to use — this
        is where a project's `org_id` actually comes from."""
        seen: dict[str, Any] = {}

        class _Engine:
            @staticmethod
            async def generate(discovery: Any, *, org_id: str, team_id: Any) -> Any:
                seen["org_id"] = org_id
                seen["team_id"] = team_id

                class _Project:
                    @staticmethod
                    def to_dict() -> dict[str, Any]:
                        return {"id": "p-1", "org_id": org_id}

                return _Project()

        monkeypatch.setattr(design_routes, "get_design_engine", lambda: _Engine())
        monkeypatch.setattr(design_routes, "get_design_store", lambda: object())
        answer = await design_routes.create_design_project(_Request(org_id="org-7"), object())
        assert seen == {"org_id": "org-7", "team_id": None}
        assert answer["org_id"] == "org-7"

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    async def test_creating_without_persistence_is_unavailable_before_engine_runs(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        class _Engine:
            @staticmethod
            async def generate(*a: Any, **k: Any) -> Any:
                nonlocal called
                called = True
                raise AssertionError("must not prepare a project without persistence")

        monkeypatch.setattr(design_routes, "get_design_store", lambda: None)
        monkeypatch.setattr(design_routes, "get_design_engine", lambda: _Engine())
        with pytest.raises(HTTPException) as raised:
            await design_routes.create_design_project(_Request(org_id="org-7"), object())
        assert raised.value.status_code == 503
        assert "persistence unavailable" in str(raised.value.detail).lower()
        assert called is False

    @pytest.mark.ac("SPEC-083026-6bc5/AC-2")
    async def test_creating_a_project_with_a_blank_request_scope_is_refused(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And it is refused before the engine is asked to generate anything:
        a blank scope is not a project to be created in the default one."""
        called: list[Any] = []

        class _Engine:
            @staticmethod
            async def generate(*a: Any, **k: Any) -> Any:
                called.append(a)
                raise AssertionError("must not be reached")

        monkeypatch.setattr(design_routes, "get_design_engine", lambda: _Engine())
        with pytest.raises(HTTPException) as raised:
            await design_routes.create_design_project(_Request(org_id=""), object())
        assert raised.value.status_code == 403
        assert called == []
