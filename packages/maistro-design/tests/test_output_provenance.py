"""A design output names the execution that produced it (#709).

`design_outputs` is the engine's one persisted artifact table, and it shipped an
artifact to a user with no record of what made it. These drive
`PgDesignProjectStore` against a session double for the same reason
`test_project_scope.py` does: what is under test is the parameters the store
binds, and a server would not make that any more visible.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from maistro.observability.correlation import bind_execution_context
from maistro_design.stores import PgDesignProjectStore
from maistro_design.trust import TrustTier
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignOutput,
    DesignProject,
    OutputFormat,
)

pytestmark = [pytest.mark.contract("behavioral")]


def _factory() -> tuple[Any, Any]:
    result = MagicMock()
    result.rowcount = 1
    result.fetchone.return_value = None
    result.fetchall.return_value = []
    session = AsyncMock()
    session.execute.return_value = result

    @asynccontextmanager
    async def make() -> Any:
        yield session

    return make, session


def _output(**overrides: Any) -> DesignOutput:
    fields: dict[str, Any] = {
        "root": ArtifactNode(
            key="root",
            kind=ArtifactKind.FILE,
            format=OutputFormat.HTML,
            value="<main>hello</main>",
        ),
        "trust_tier": TrustTier.T3,
    }
    fields.update(overrides)
    return DesignOutput(**fields)


def _project(outputs: list[DesignOutput]) -> DesignProject:
    return DesignProject(
        id="p-1",
        name="Login Flow",
        skill_slug="login-flow",
        design_system_slug="default",
        org_id="org-1",
        trust_tier=TrustTier.T3,
        outputs=outputs,
    )


def _output_params(session: Any) -> list[dict[str, Any]]:
    """The bound parameters of every `design_outputs` insert the store issued."""
    return [
        call.args[1]
        for call in session.execute.call_args_list
        if len(call.args) > 1
        and isinstance(call.args[1], dict)
        and "run_id" in call.args[1]
        and "format" in call.args[1]
    ]


class TestAnArtifactNamesItsProducer:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-2")
    async def test_an_output_written_inside_an_attempt_carries_it(self) -> None:
        make, session = _factory()
        with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
            await PgDesignProjectStore(session_factory=make).create(_project([_output()]))

        [params] = _output_params(session)
        assert params["run_id"] == "r-1"
        assert params["node_run_id"] == "nr-1"
        assert params["attempt_id"] == "a-1"

    @pytest.mark.ac("SPEC-083026-b2b5/AC-4")
    async def test_an_output_written_outside_an_execution_binds_null(self) -> None:
        """Not `""`. An empty string names a Run whose id is empty, which is a
        claim; NULL says no execution was in scope."""
        make, session = _factory()
        await PgDesignProjectStore(session_factory=make).create(_project([_output()]))

        [params] = _output_params(session)
        assert params["run_id"] is None
        assert params["node_run_id"] is None
        assert params["attempt_id"] is None

    async def test_a_producer_the_caller_named_is_kept(self) -> None:
        make, session = _factory()
        with bind_execution_context(run_id="ambient"):
            await PgDesignProjectStore(session_factory=make).create(
                _project([_output(run_id="named")])
            )

        [params] = _output_params(session)
        assert params["run_id"] == "named"

    async def test_each_output_is_attributed_separately(self) -> None:
        """Outputs of one project can come from different Attempts — a
        refinement pass is a second Attempt over the same project — so the
        producer is resolved per output, not once per project."""
        make, session = _factory()
        with bind_execution_context(run_id="r-1", attempt_id="a-first"):
            await PgDesignProjectStore(session_factory=make).create(
                _project([_output(), _output(attempt_id="a-second")])
            )

        first, second = _output_params(session)
        assert first["attempt_id"] == "a-first"
        assert second["attempt_id"] == "a-second"
        assert first["run_id"] == second["run_id"] == "r-1"


class TestTheProducerSurvivesTheReadBack:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-2")
    def test_a_row_carrying_a_producer_maps_onto_the_output(self) -> None:
        from maistro_design.stores import _coerce_design_output

        output = _coerce_design_output(
            {
                "format": "html",
                "content": "<main>hello</main>",
                "url": None,
                "trust_tier": "t3",
                "metadata_json": None,
                "run_id": "r-1",
                "node_run_id": "nr-1",
                "attempt_id": "a-1",
            }
        )
        assert (output.run_id, output.node_run_id, output.attempt_id) == ("r-1", "nr-1", "a-1")

    def test_a_row_with_no_producer_maps_onto_blanks_not_none(self) -> None:
        """The columns are nullable and the dataclass fields are not: a row with
        no producer reads back as an output naming none."""
        from maistro_design.stores import _coerce_design_output

        output = _coerce_design_output(
            {
                "format": "html",
                "content": "<main>hello</main>",
                "url": None,
                "trust_tier": "t3",
                "metadata_json": None,
                "run_id": None,
                "node_run_id": None,
                "attempt_id": None,
            }
        )
        assert (output.run_id, output.node_run_id, output.attempt_id) == ("", "", "")

    def test_a_row_predating_the_columns_still_maps(self) -> None:
        """A read from a database migrated before 025 has no such keys at all."""
        from maistro_design.stores import _coerce_design_output

        output = _coerce_design_output(
            {
                "format": "html",
                "content": "<main>hello</main>",
                "url": None,
                "trust_tier": "t3",
                "metadata_json": None,
            }
        )
        assert output.run_id == ""
