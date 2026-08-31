"""No production reader reaches into the outcome store's internals (#696).

The thumbs signal was read as `getattr(store, "_outcomes", [])` in two places.
`_outcomes` is a private list `InMemoryOutcomeStore` has and neither durable
store does, so the expression is not a bug that fails -- it is a bug that
returns `[]`. Wiring the container's durable store, which is the whole point of
this change, would have emptied the optimizer's user-satisfaction signal and
the topology comparison's thumbs column with nothing raised anywhere.

The source scan is the guard that keeps it gone: a future reader reaching for
the attribute again would otherwise pass every behavioural test in this suite,
because those all run against the in-memory store that has it.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_PRIVATE = "_outcomes"


def _reads_the_private_list(source: str) -> bool:
    """Whether this module actually reaches for the attribute.

    Parsed, not grepped, and both earlier versions of this predicate are the
    argument for that. A plain substring test flagged `list_outcomes`,
    `pg_outcomes` and `sqlite_outcomes` -- sixteen files, none of them the
    defect. Tightening it to a word boundary fixed those and then flagged the
    docstrings that explain the defect, so writing down what went wrong tripped
    the guard against it. The obvious repair to either is an allowlist, which
    would have had to name `optimizer.py` and `topology_compare.py` and so
    would have excused exactly the two readers this exists to catch.

    An access is `x._outcomes` or `getattr(x, "_outcomes", ...)`. Neither
    appears in a comment or a docstring, because neither is code.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == _PRIVATE:
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == _PRIVATE
        ):
            return True
    return False


_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_REPO = _BACKEND.parents[2]
#: The one module allowed to touch `_outcomes`: the store that defines it.
_OWNER = _REPO / "packages/maistro-core/src/maistro/memory/outcomes.py"

pytestmark = [pytest.mark.contract("behavioral")]


def _sources() -> list[pathlib.Path]:
    """Every production Python file, tests excluded.

    Tests may construct an `InMemoryOutcomeStore` and inspect it; that is
    reading a concrete class they built, not a store handed to them through a
    protocol.
    """
    roots = (
        _REPO / "packages/hive-conductor/backend",
        _REPO / "packages/maistro-core/src",
    )
    return [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "tests" not in path.parts and "test_" not in path.name
    ]


class TestThePrivateListIsNotReadOutsideItsOwner:
    @pytest.mark.ac("SPEC-083026-58de/AC-4")
    def test_no_production_module_reads_outcomes_directly(self) -> None:
        offenders = [
            str(path.relative_to(_REPO))
            for path in _sources()
            if path != _OWNER and _reads_the_private_list(path.read_text(encoding="utf-8"))
        ]

        assert offenders == [], (
            "read thumbs through `OutcomeStore.list_thumbs`; `_outcomes` exists "
            "only on the in-memory store, so these readers go silently empty "
            "against PostgreSQL or SQLite"
        )

    @pytest.mark.ac("SPEC-083026-58de/AC-4")
    def test_the_scan_actually_reaches_the_two_former_offenders(self) -> None:
        """A guard whose corpus is empty guards nothing.

        Both files that held the defect must be inside the scanned set, or the
        assertion above would pass by never looking at them.
        """
        scanned = {str(p.relative_to(_REPO)) for p in _sources()}

        assert "packages/hive-conductor/backend/services/optimizer.py" in scanned
        assert "packages/hive-conductor/backend/services/topology_compare.py" in scanned

    @pytest.mark.ac("SPEC-083026-58de/AC-4")
    def test_the_pattern_matches_the_attribute_and_not_its_lookalikes(self) -> None:
        """Both false-positive classes, and the true positives, pinned.

        The last case is the one that matters most: the modules that fixed this
        defect all describe it in their docstrings, so a scan that read text
        would be tripped by its own explanation.
        """
        assert _reads_the_private_list('getattr(store, "_outcomes", [])')
        assert _reads_the_private_list("self._outcomes.append(o)")
        assert not _reads_the_private_list("await store.list_outcomes(days=7)")
        assert not _reads_the_private_list("from maistro.persistence.pg_outcomes import X")
        assert not _reads_the_private_list('"""We used to read store._outcomes here."""')


class TestTheSetterHasAProductionCaller:
    """`set_outcome_store` had none, which is why the durable store was unused.

    #236 gates DI attributes that are wired and never read; this is the same
    defect one level up -- a seam built for a call that was never made, with a
    docstring describing the bridge that would make it.
    """

    @pytest.mark.ac("SPEC-083026-58de/AC-6")
    def test_the_engine_binds_the_containers_store(self) -> None:
        from services import engine as engine_module

        source = pathlib.Path(engine_module.__file__).read_text(encoding="utf-8")

        assert "set_outcome_store(" in source
        assert "_wire_outcome_store" in source

    @pytest.mark.ac("SPEC-083026-58de/AC-6")
    async def test_starting_with_a_container_binds_its_store(self) -> None:
        """Through `_wire_outcome_store` itself, not by reading the source.

        The scan above proves the call is written; this proves it does what the
        name says when a container is present.
        """
        from services import feedback_service
        from services.engine import EngineService

        durable = object()
        service = EngineService()
        service._agent_port = type(
            "_Port", (), {"container": type("_C", (), {"outcome_store": durable})()}
        )()
        before = feedback_service.get_outcome_store()
        try:
            service._wire_outcome_store()
            assert feedback_service.get_outcome_store() is durable
        finally:
            feedback_service.set_outcome_store(before)

    @pytest.mark.ac("SPEC-083026-58de/AC-6")
    async def test_no_container_installs_a_hive_local_store(self) -> None:
        """Without the bridge a thumb still records, into memory, deterministically.

        Binding `None` here would turn every feedback write into an
        AttributeError in exactly the dev and test modes the Hive-local default
        exists to serve.
        """
        from services import feedback_service
        from services.engine import EngineService

        from maistro.memory.outcomes import InMemoryOutcomeStore

        before = feedback_service.get_outcome_store()
        try:
            EngineService()._wire_outcome_store()

            assert isinstance(feedback_service.get_outcome_store(), InMemoryOutcomeStore)
        finally:
            feedback_service.set_outcome_store(before)

    @pytest.mark.ac("SPEC-083026-58de/AC-6")
    async def test_a_start_without_a_bridge_does_not_inherit_the_last_container(self) -> None:
        """The second start in one process, which the early return got wrong.

        An engine restart, or a configuration retry that falls back to the
        stub, would otherwise leave the module global pointing at the previous
        container's store -- so feedback would keep being written to a database
        this engine no longer owns, or to a closed connection.
        """
        from services import feedback_service
        from services.engine import EngineService

        from maistro.memory.outcomes import InMemoryOutcomeStore

        durable = object()
        bound = EngineService()
        bound._agent_port = type(
            "_Port", (), {"container": type("_C", (), {"outcome_store": durable})()}
        )()
        before = feedback_service.get_outcome_store()
        try:
            bound._wire_outcome_store()
            assert feedback_service.get_outcome_store() is durable

            EngineService()._wire_outcome_store()

            assert feedback_service.get_outcome_store() is not durable
            assert isinstance(feedback_service.get_outcome_store(), InMemoryOutcomeStore)
        finally:
            feedback_service.set_outcome_store(before)


class TestTheBridgeTellsTheContainerWhichDatabase:
    """Binding the container's store is only durability if the container has one.

    `MaistroCoreBridge` builds `AgentConfig` directly rather than through
    `config.loader`, and left `database_url` at its empty default. So
    `create_container` took the ephemeral branch and built an
    `InMemoryOutcomeStore` however the deployment was configured -- and this
    change would then have bound *that* as the durable store, leaving every
    thumb still lost on restart while claiming otherwise (Codex, #696).
    """

    @pytest.mark.ac("SPEC-083026-58de/AC-6")
    def test_the_bridge_resolves_the_database_url(self) -> None:
        """Asserted on the source, because reaching the call needs a live LLM.

        `start()` builds the config and immediately opens a container and an
        HTTP client against it. What this pins is the omission itself: the
        argument is passed, and it is passed from the shared resolver rather
        than from a Hive-only setting that would be a second answer to
        "which database".
        """
        import ast

        from adapters import maistro_core

        source = pathlib.Path(maistro_core.__file__).read_text(encoding="utf-8")
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "AgentConfig"
        ]

        assert calls, "the bridge no longer builds an AgentConfig; re-target this guard"
        for call in calls:
            supplied = {kw.arg for kw in call.keywords}
            assert "database_url" in supplied, (
                "the container decides its backend from `config.database_url`; "
                "omitting it makes every store ephemeral whatever the deployment set"
            )
        assert "resolve_database_url" in source

    @pytest.mark.ac("SPEC-083026-58de/AC-6")
    def test_an_empty_url_still_yields_an_in_memory_store(self) -> None:
        """The resolver returning nothing is a real answer, not a failure.

        A deployment that configures no database gets ephemeral stores, and
        `_wire_outcome_store` then binds an in-memory one -- which is the
        documented fallback, not a downgrade this change introduced.
        """
        from maistro.config.database import resolve_database_url

        assert resolve_database_url({}) == ""
