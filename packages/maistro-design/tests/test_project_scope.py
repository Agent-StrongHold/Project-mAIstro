"""A design project's scope is writable, and is enforced on every read (#326).

`design_projects.org_id` was a foreign key to an `orgs` table that migration 003
creates and nothing populates, so on a database migrated to head the only
`org_id` the Design Studio supplies could not be inserted at all — #177's repair
turned "the schema cannot migrate" into "the schema migrates but the product
cannot write". At the same time `get`, `update` and `delete` matched on project
id alone, so any authenticated caller could read, edit or delete another scope's
project.

These tests hold both halves: a project naming the scope the product actually
has is writable, and a project in another scope is not reachable.

The store tests drive `PgDesignProjectStore` against session doubles rather than
a server, because what is under test is the SQL the store composes and the
guards around it. `tests/migrations/test_migration_chain.py` holds the half that
needs a real PostgreSQL, since a `CHECK` constraint is only a claim until a
server enforces it.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from maistro_design.protocols import DesignProjectStore
from maistro_design.stores import PgDesignProjectStore
from maistro_design.trust import TrustTier
from maistro_design.types import (
    DesignProject,
    DesignProjectNotFoundError,
    DesignScopeError,
)

pytestmark = [pytest.mark.contract("boundary")]


def _factory(*, rowcount: int = 1, row: object | None = None):
    """A session double, plus the session so a test can read what was executed.

    The result is a `MagicMock`, not an `AsyncMock` child: SQLAlchemy's `Result`
    is awaited once and then read synchronously, and an `AsyncMock`'s `fetchone`
    hands back a coroutine — which is truthy, so `if not project_row` would take
    the wrong branch and a test for "reads as absent" would pass against a store
    that returned the row.
    """
    result = MagicMock()
    result.rowcount = rowcount
    result.fetchone.return_value = row
    result.fetchall.return_value = []
    session = AsyncMock()
    session.execute.return_value = result

    @asynccontextmanager
    async def make():
        yield session

    return make, session


def _project(*, org_id: str = "org-1", project_id: str = "p-1") -> DesignProject:
    return DesignProject(
        id=project_id,
        name="Login Flow",
        skill_slug="login-flow",
        design_system_slug="default",
        org_id=org_id,
        trust_tier=TrustTier.T3,
    )


class TestAProjectMustNameItsScope:
    @pytest.mark.ac("SPEC-083026-6bc5/AC-2")
    async def test_create_refuses_a_scope_less_project(self) -> None:
        make, session = _factory()
        with pytest.raises(DesignScopeError):
            await PgDesignProjectStore(session_factory=make).create(_project(org_id=""))
        session.execute.assert_not_awaited()

    @pytest.mark.ac("SPEC-083026-6bc5/AC-2")
    async def test_update_refuses_a_scope_less_project(self) -> None:
        make, session = _factory()
        with pytest.raises(DesignScopeError):
            await PgDesignProjectStore(session_factory=make).update(_project(org_id=""))
        session.execute.assert_not_awaited()

    @pytest.mark.ac("SPEC-083026-6bc5/AC-2")
    @pytest.mark.parametrize("call", ["get", "delete", "list_by_org", "list_by_skill"])
    async def test_every_scoped_read_refuses_a_blank_scope(self, call: str) -> None:
        make, session = _factory()
        store = PgDesignProjectStore(session_factory=make)
        invocations = {
            "get": lambda: store.get("p-1", org_id=""),
            "delete": lambda: store.delete("p-1", org_id=""),
            "list_by_org": lambda: store.list_by_org(""),
            "list_by_skill": lambda: store.list_by_skill("login-flow", ""),
        }
        with pytest.raises(DesignScopeError):
            await invocations[call]()
        session.execute.assert_not_awaited()


class TestAReadOutsideTheScopeFindsNothing:
    @pytest.mark.ac("SPEC-083026-6bc5/AC-3")
    async def test_get_matches_on_the_scope_as_well_as_the_id(self) -> None:
        make, session = _factory(row=None)
        assert await PgDesignProjectStore(session_factory=make).get("p-1", org_id="org-2") is None
        statement, params = session.execute.await_args.args
        assert "org_id = :org_id" in str(statement)
        assert params == {"id": "p-1", "org_id": "org-2"}

    @pytest.mark.ac("SPEC-083026-6bc5/AC-3")
    async def test_absence_is_the_answer_rather_than_a_refusal(self) -> None:
        """A raise here would confirm the project exists somewhere, which is the
        scoped fact the check withholds."""
        make, _ = _factory(row=None)
        assert await PgDesignProjectStore(session_factory=make).get("p-1", org_id="org-2") is None


class TestAWriteOutsideTheScopeIsRefused:
    @pytest.mark.ac("SPEC-083026-6bc5/AC-4")
    async def test_an_update_that_matched_nothing_raises(self) -> None:
        make, session = _factory(rowcount=0)
        with pytest.raises(DesignProjectNotFoundError):
            await PgDesignProjectStore(session_factory=make).update(_project())
        session.commit.assert_not_awaited()

    @pytest.mark.ac("SPEC-083026-6bc5/AC-4")
    async def test_an_update_carries_the_scope_into_its_where_clause(self) -> None:
        make, session = _factory(rowcount=1)
        await PgDesignProjectStore(session_factory=make).update(_project(org_id="org-7"))
        statement, params = session.execute.await_args.args
        assert "WHERE id = :id AND org_id = :org_id" in str(statement)
        assert params["org_id"] == "org-7"

    @pytest.mark.ac("SPEC-083026-6bc5/AC-4")
    async def test_a_delete_carries_the_scope_into_its_where_clause(self) -> None:
        make, session = _factory()
        await PgDesignProjectStore(session_factory=make).delete("p-1", org_id="org-7")
        statement, params = session.execute.await_args.args
        assert "org_id = :org_id" in str(statement)
        assert params == {"id": "p-1", "org_id": "org-7"}

    @pytest.mark.ac("SPEC-083026-6bc5/AC-4")
    async def test_a_create_writes_the_scope_it_was_given(self) -> None:
        make, session = _factory()
        await PgDesignProjectStore(session_factory=make).create(_project(org_id="org-7"))
        statement, params = session.execute.await_args_list[0].args
        assert "INSERT INTO design_projects" in str(statement)
        assert params["org_id"] == "org-7"


class TestEverySingleProjectOperationTakesAScope:
    """Read from the signatures, so a method added later is held to the rule.

    The defect was not that one call site forgot the scope; it was that the
    protocol let it. A test naming today's three methods would pass for a fourth
    that reintroduced the shape.
    """

    #: Operations addressing one project by id. The list methods already took
    #: `org_id` positionally before #326 and keep doing so.
    BY_ID = ("get", "delete")

    @pytest.mark.ac("SPEC-083026-6bc5/AC-5")
    @pytest.mark.parametrize("name", BY_ID)
    def test_the_protocol_requires_a_keyword_only_scope(self, name: str) -> None:
        parameters = inspect.signature(getattr(DesignProjectStore, name)).parameters
        assert "org_id" in parameters, f"{name} addresses one project without a scope"
        assert parameters["org_id"].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters["org_id"].default is inspect.Parameter.empty, (
            "a default here is a default the next caller omits"
        )

    @pytest.mark.ac("SPEC-083026-6bc5/AC-5")
    @pytest.mark.parametrize("name", BY_ID)
    def test_the_implementation_matches_the_protocol(self, name: str) -> None:
        assert inspect.signature(getattr(PgDesignProjectStore, name)).parameters.keys() == (
            inspect.signature(getattr(DesignProjectStore, name)).parameters.keys()
        )

    @pytest.mark.ac("SPEC-083026-6bc5/AC-5")
    def test_no_sql_in_the_store_selects_a_project_without_its_scope(self) -> None:
        """The rule the signatures cannot state: a statement naming
        `design_projects` by id has to name the scope too."""
        source = pathlib.Path(inspect.getfile(PgDesignProjectStore)).read_text()
        statements = [
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "design_projects" in node.value
            and "WHERE" in node.value.upper()
        ]
        assert statements, "no statements found; this check would prove nothing"
        for statement in statements:
            assert "org_id" in statement, f"unscoped statement: {statement.strip()[:120]}"


class TestTheHttpSurfacePassesTheScopeDown:
    """Parsed from the Conductor route, which this package cannot import.

    `maistro-design` does not depend on `hive-conductor` and must not start to;
    the route is read as a file for the same reason the frontend criteria in
    other specs are.
    """

    SOURCE = (
        pathlib.Path(__file__).resolve().parents[2]
        / "hive-conductor"
        / "backend"
        / "routes"
        / "design.py"
    )

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    def test_every_store_get_in_the_route_carries_a_scope(self) -> None:
        calls = [
            node
            for node in ast.walk(ast.parse(self.SOURCE.read_text()))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "store"
        ]
        assert calls, "no store.get calls found; this check would prove nothing"
        for call in calls:
            assert "org_id" in {kw.arg for kw in call.keywords}

    @pytest.mark.ac("SPEC-083026-6bc5/AC-6")
    def test_the_deployment_scope_still_wins_over_the_conductor_default(self) -> None:
        source = self.SOURCE.read_text()
        resolver = source[source.index("def _get_org_id") : source.index("@router.post")]
        assert '"org_id"' in resolver or "request" in resolver
        assert "CONDUCTOR_ORG_ID" in resolver, "the fallback is a named constant, not a literal"
        assert '"default-org"' not in resolver, "the literal moved to the constant's definition"
