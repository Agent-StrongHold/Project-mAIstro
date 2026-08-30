"""The canonical execution ids reach logs, spans and events (#707).

Behavioural throughout: every case drives the real seam and reads what a
reader would actually see — a rendered log line, the attributes set on a span,
the envelope a store persisted — rather than asserting that a function was
called with the right arguments.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import structlog

from maistro.events.envelope import EventEnvelope, InMemoryEventStore, correlated
from maistro.observability.correlation import (
    EMPTY,
    FIELD_NAMES,
    ExecutionContext,
    bind_execution_context,
    current_execution_context,
    execution_context_processor,
)

pytestmark = [pytest.mark.contract("behavioral")]


# ─── The context itself ───────────────────────────────────────────────────────


class TestBindingIsAdditive:
    """What a caller does not name, it inherits."""

    def test_an_inner_binding_keeps_the_outer_ids(self) -> None:
        with (
            bind_execution_context(run_id="run-1", workspace_id="ws-1"),
            bind_execution_context(node_run_id="nr-1"),
        ):
            seen = current_execution_context()
        assert seen.run_id == "run-1"
        assert seen.workspace_id == "ws-1"
        assert seen.node_run_id == "nr-1"

    def test_an_inner_binding_may_override_an_outer_id(self) -> None:
        """A child Run is a different Run, and says so."""
        with bind_execution_context(run_id="parent"):
            with bind_execution_context(run_id="child"):
                assert current_execution_context().run_id == "child"
            assert current_execution_context().run_id == "parent"

    def test_three_levels_compose(self) -> None:
        with (
            bind_execution_context(run_id="r"),
            bind_execution_context(node_run_id="n"),
            bind_execution_context(attempt_id="a"),
        ):
            seen = current_execution_context()
        assert (seen.run_id, seen.node_run_id, seen.attempt_id) == ("r", "n", "a")


class TestABlankNeverErases:
    """A seam that cannot resolve an id must not be worse than one that
    does not try."""

    @pytest.mark.parametrize("blank", ["", None])
    def test_a_blank_value_leaves_the_inherited_id_standing(self, blank: str | None) -> None:
        with bind_execution_context(run_id="run-1"), bind_execution_context(run_id=blank):
            assert current_execution_context().run_id == "run-1"

    def test_a_binding_of_only_blanks_is_the_same_context(self) -> None:
        with (
            bind_execution_context(run_id="run-1") as outer,
            bind_execution_context(node_run_id="", attempt_id=None) as inner,
        ):
            assert inner == outer

    def test_a_blank_on_an_unbound_context_stays_absent_rather_than_empty(self) -> None:
        with bind_execution_context(run_id=""):
            assert "run_id" not in current_execution_context().as_log_fields()


class TestTheScopeIsTheLifetime:
    def test_the_context_is_empty_before_anything_binds(self) -> None:
        assert current_execution_context() == EMPTY

    def test_the_binding_is_gone_after_the_block(self) -> None:
        with bind_execution_context(run_id="run-1"):
            pass
        assert current_execution_context().run_id == ""

    def test_the_binding_is_gone_after_an_exception(self) -> None:
        with pytest.raises(RuntimeError), bind_execution_context(run_id="run-1"):
            raise RuntimeError("boom")
        assert current_execution_context().run_id == ""

    async def test_a_sibling_task_does_not_see_a_later_binding(self) -> None:
        """Tasks copy the context at creation. A task started before the bind
        must not acquire ids that belong to work it is not doing."""
        started = asyncio.Event()
        release = asyncio.Event()
        seen: list[str] = []

        async def sibling() -> None:
            started.set()
            await release.wait()
            seen.append(current_execution_context().run_id)

        task = asyncio.create_task(sibling())
        await started.wait()
        with bind_execution_context(run_id="run-1"):
            release.set()
            await task
        assert seen == [""]

    async def test_a_task_started_inside_the_scope_inherits_it(self) -> None:
        seen: list[str] = []

        async def child() -> None:
            seen.append(current_execution_context().run_id)

        with bind_execution_context(run_id="run-1"):
            await asyncio.create_task(child())
        assert seen == ["run-1"]

    async def test_a_child_task_binding_does_not_escape_to_its_parent(self) -> None:
        async def child() -> None:
            with bind_execution_context(attempt_id="leaked"):
                pass

        with bind_execution_context(run_id="run-1"):
            await asyncio.create_task(child())
            assert current_execution_context().attempt_id == ""


class TestAnUnknownIdIsRefused:
    def test_a_misspelled_field_raises_rather_than_correlating_nothing(self) -> None:
        with (
            pytest.raises(ValueError, match="not correlation ids: noderun_id"),
            bind_execution_context(noderun_id="nr-1"),
        ):
            pass

    def test_the_error_names_the_ids_that_do_exist(self) -> None:
        with pytest.raises(ValueError, match="node_run_id"):
            ExecutionContext().merged(nope="x")

    def test_every_declared_field_name_is_bindable(self) -> None:
        """`FIELD_NAMES` and the dataclass cannot drift apart unnoticed."""
        with bind_execution_context(**dict.fromkeys(FIELD_NAMES, "v")) as ctx:
            assert ctx.as_log_fields() == dict.fromkeys(FIELD_NAMES, "v")


class TestBlankIdsAreAbsentNotEmpty:
    def test_only_the_ids_that_are_set_are_reported(self) -> None:
        with bind_execution_context(run_id="run-1"):
            assert current_execution_context().as_log_fields() == {"run_id": "run-1"}

    def test_an_all_blank_context_is_falsy(self) -> None:
        assert not ExecutionContext()

    def test_one_id_makes_a_context_truthy(self) -> None:
        assert ExecutionContext(session_id="s")


# ─── Logs ─────────────────────────────────────────────────────────────────────


class TestTheProcessorMergesOntoLogEvents:
    def test_the_active_ids_land_on_the_event(self) -> None:
        with bind_execution_context(run_id="run-1", attempt_id="a-1"):
            out = execution_context_processor(None, "info", {"event": "x"})
        assert out == {"event": "x", "run_id": "run-1", "attempt_id": "a-1"}

    def test_an_explicit_field_at_the_call_site_wins(self) -> None:
        """A line logging *about* another Run knows more than the ambient
        context does."""
        with bind_execution_context(run_id="ambient"):
            out = execution_context_processor(None, "info", {"event": "x", "run_id": "named"})
        assert out["run_id"] == "named"

    def test_nothing_is_added_when_nothing_is_bound(self) -> None:
        assert execution_context_processor(None, "info", {"event": "x"}) == {"event": "x"}


class TestARenderedLogLineCarriesTheIds:
    """The end a reader actually sees: JSON on stderr with the ids in it."""

    @staticmethod
    def _render(**bind: str) -> dict[str, Any]:
        factory = structlog.testing.CapturingLoggerFactory()
        structlog.configure(
            processors=[execution_context_processor, structlog.processors.JSONRenderer()],
            logger_factory=factory,
            cache_logger_on_first_use=False,
        )
        try:
            log = structlog.get_logger()
            with bind_execution_context(**bind):
                log.info("node_started")
        finally:
            structlog.reset_defaults()
        return json.loads(factory.logger.calls[0].args[0])

    def test_a_line_inside_an_attempt_names_run_node_run_and_attempt(self) -> None:
        line = self._render(run_id="r-1", node_run_id="nr-1", attempt_id="a-1")
        assert line["run_id"] == "r-1"
        assert line["node_run_id"] == "nr-1"
        assert line["attempt_id"] == "a-1"

    def test_a_line_outside_any_execution_names_none_of_them(self) -> None:
        line = self._render()
        assert "run_id" not in line
        assert line["event"] == "node_started"


# ─── Spans ────────────────────────────────────────────────────────────────────


class _Span:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def record_exception(self, exc: BaseException) -> None:  # pragma: no cover - unused
        raise AssertionError(f"unexpected exception recorded: {exc}")

    def set_status(self, status: Any) -> None:  # pragma: no cover - unused
        raise AssertionError("unexpected status")


class TestSpansCarryTheIds:
    @staticmethod
    async def _run_traced(monkeypatch: pytest.MonkeyPatch, **bind: str) -> _Span:
        import contextlib

        from maistro.observability import tracing

        span = _Span()

        class _Tracer:
            @contextlib.contextmanager
            def start_as_current_span(self, name: str) -> Any:
                assert name == "conductor"
                yield span

        monkeypatch.setattr(tracing, "_get_tracer", lambda: _Tracer())

        @tracing.trace_agent("conductor")
        async def handle() -> str:
            return "done"

        with bind_execution_context(**bind):
            assert await handle() == "done"
        return span

    async def test_the_span_names_the_execution_it_traced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        span = await self._run_traced(monkeypatch, run_id="r-1", attempt_id="a-1")
        assert span.attributes["maistro.run_id"] == "r-1"
        assert span.attributes["maistro.attempt_id"] == "a-1"

    async def test_an_unset_id_is_not_written_as_an_empty_attribute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        span = await self._run_traced(monkeypatch, run_id="r-1")
        assert "maistro.node_run_id" not in span.attributes

    async def test_tracing_still_works_with_no_context_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        span = await self._run_traced(monkeypatch)
        assert span.attributes == {"maistro.output_preview": "done"}


# ─── Events ───────────────────────────────────────────────────────────────────


class TestABlankEnvelopeFieldIsFilledFromContext:
    def test_the_ids_the_producer_omitted_are_filled(self) -> None:
        with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
            event = correlated(EventEnvelope(type="x", workspace_id="ws-1"))
        assert event.run_id == "r-1"
        assert event.node_run_id == "nr-1"
        assert event.attempt_id == "a-1"

    def test_correlation_id_falls_back_to_the_run(self) -> None:
        with bind_execution_context(run_id="r-1"):
            event = correlated(EventEnvelope(type="x", workspace_id="ws-1"))
        assert event.correlation_id == "r-1"

    def test_an_id_the_producer_set_is_never_overwritten(self) -> None:
        """An event *about* another Run says something the context does not."""
        with bind_execution_context(run_id="ambient"):
            event = correlated(EventEnvelope(type="x", workspace_id="ws-1", run_id="named"))
        assert event.run_id == "named"

    def test_a_correlation_id_the_producer_set_is_kept(self) -> None:
        with bind_execution_context(run_id="ambient"):
            event = correlated(
                EventEnvelope(type="x", workspace_id="ws-1", correlation_id="chosen")
            )
        assert event.correlation_id == "chosen"

    def test_nothing_changes_when_no_context_is_bound(self) -> None:
        original = EventEnvelope(type="x", workspace_id="ws-1")
        assert correlated(original) is original

    def test_an_alternate_stream_scope_is_left_alone(self) -> None:
        """Filling `workspace_id` here would move the event to another stream,
        or raise on the envelope's own mutual-exclusion rule."""
        with bind_execution_context(workspace_id="ws-1"):
            event = correlated(EventEnvelope(type="x", stream_scope="system"))
        assert event.workspace_id == ""
        assert event.stream_id == "scope:system"

    def test_the_payload_survives_the_fill(self) -> None:
        with bind_execution_context(run_id="r-1"):
            event = correlated(EventEnvelope(type="x", workspace_id="ws-1", payload={"k": [1, 2]}))
        assert event.payload == {"k": [1, 2]}


class TestAppendCorrelatesWhatItPersists:
    async def test_a_stored_event_carries_the_run_that_produced_it(self) -> None:
        store = InMemoryEventStore()
        with bind_execution_context(run_id="r-1", node_run_id="nr-1"):
            await store.append(EventEnvelope(type="x", workspace_id="ws-1", event_id="e1"))
        stored = await store.get("e1")
        assert stored is not None
        assert (stored.run_id, stored.node_run_id) == ("r-1", "nr-1")

    async def test_an_event_already_present_is_returned_as_it_was_stored(self) -> None:
        """Re-appending must not re-correlate: the first write is the record."""
        store = InMemoryEventStore()
        with bind_execution_context(run_id="first"):
            await store.append(EventEnvelope(type="x", workspace_id="ws-1", event_id="e1"))
        with bind_execution_context(run_id="second"):
            again = await store.append(EventEnvelope(type="x", workspace_id="ws-1", event_id="e1"))
        assert again.run_id == "first"

    async def test_an_uncorrelated_append_still_works(self) -> None:
        store = InMemoryEventStore()
        stored = await store.append(EventEnvelope(type="x", workspace_id="ws-1", event_id="e1"))
        assert stored.run_id == ""
        assert stored.sequence == 1


# ─── One vocabulary ───────────────────────────────────────────────────────────


_BANNED = frozenset({"bind_contextvars", "clear_contextvars", "unbind_variables"})

#: The trees that carry production code and could acquire a second vocabulary.
#: `hive-conductor/backend` is not a `src` layout but is production code all the
#: same; its `tests` subtree is excluded because a test may legitimately
#: demonstrate the thing being banned.
_SRC_ROOTS = (
    "packages/maistro-core/src",
    "packages/maistro-server/src",
    "packages/hive-conductor/backend",
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() and (parent / "packages").is_dir():
            return parent
    raise AssertionError("could not locate the repository root from the test file")


def _called_names(tree: ast.AST) -> set[str]:
    """Return the names of functions *called* in `tree`.

    Syntax, not substrings. A word-boundary scan flags the prose that explains
    why the ban exists, so writing the reason down would trip the guard against
    it -- the same trap #700's `_outcomes` guard fell into twice. A reference
    passed as a value (`structlog.contextvars.merge_contextvars` in a processor
    list) is not a call and is not flagged.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)
    return names


def _scanned_files() -> list[Path]:
    root = _repo_root()
    return sorted(
        path
        for src in _SRC_ROOTS
        for path in (root / src).rglob("*.py")
        if "third_party" not in path.parts and "tests" not in path.parts
    )


class TestOneCorrelationVocabulary:
    """structlog's own contextvars are a second, competing place to put an id.

    Keeping them out is what makes "the execution context is where correlation
    lives" a fact rather than a convention: an id bound there reaches log lines
    and neither spans nor events, which is the split this change closed.
    """

    def test_no_source_file_binds_structlog_contextvars_directly(self) -> None:
        offenders = {
            str(path.relative_to(_repo_root())): sorted(banned)
            for path in _scanned_files()
            if (banned := _called_names(ast.parse(path.read_text())) & _BANNED)
        }
        assert offenders == {}, (
            f"bind correlation ids through maistro.observability.correlation instead: {offenders}"
        )

    def test_the_scanned_corpus_is_not_empty(self) -> None:
        """A guard whose corpus is empty guards nothing."""
        scanned = _scanned_files()
        assert len(scanned) > 100
        assert any(path.name == "middleware.py" for path in scanned)

    def test_a_reference_that_is_not_a_call_is_not_flagged(self) -> None:
        """`configure_logging` passes `merge_contextvars` as a processor, and
        must keep being allowed to."""
        source = "processors = [structlog.contextvars.merge_contextvars, other]"
        assert _called_names(ast.parse(source)) & _BANNED == set()

    def test_the_banned_call_is_actually_detected(self) -> None:
        source = "structlog.contextvars.bind_contextvars(run_id='r')"
        assert _called_names(ast.parse(source)) & _BANNED == {"bind_contextvars"}

    def test_an_imported_bare_call_is_detected_too(self) -> None:
        source = "from structlog.contextvars import bind_contextvars\nbind_contextvars(x=1)"
        assert _called_names(ast.parse(source)) & _BANNED == {"bind_contextvars"}
