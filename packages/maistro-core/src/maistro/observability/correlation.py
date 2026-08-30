"""One execution-correlation context, carried on a ContextVar (#707).

The canonical IDs already exist on the records: `EventEnvelope` declares all
nine of them and the Run/NodeRun/Attempt stores persist them. What was missing
was any way for code *inside* an execution to know which execution it was in.
`RequestIDMiddleware` bound one key, `request_id`, and only for work that
arrived over HTTP; a schedule firing or a task-queue dispatch emitted log lines
with no correlation at all, and a span opened by `trace_agent` named no Run.

Three properties are load-bearing, and each has a test that fails without it:

**Binding is additive.** `bind_execution_context(node_run_id=...)` inside a
Run-scoped context keeps the Run. The alternative — every caller restating
every id — is the arrangement that loses one, because the caller deepest in
the stack is the one least likely to hold the outer ids.

**A blank never erases.** Passing `run_id=""` or `run_id=None` leaves an
inherited `run_id` standing. A seam that does not know an id passes nothing,
and passing an id it could not resolve must not be worse than passing none.

**The scope is the lifetime.** Every binding is a context manager that resets
its own token, so a context cannot outlive the work it describes. An unbound
context reads as empty, never as whatever the last execution on this task left
behind.

This is not :class:`maistro.observability.proxy.TraceContext`, which allocates
the per-trace sequence numbers of the ADR-037 record/replay proxies and is
passed by hand between two proxies that must agree. That one is a counter
shared between two collaborators; this one is ambient identity.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, MutableMapping
from contextvars import ContextVar
from dataclasses import dataclass, fields, replace
from typing import Any

#: The canonical correlation ids, in the order a reader follows them.
FIELD_NAMES: tuple[str, ...] = (
    "workspace_id",
    "project_id",
    "run_id",
    "node_run_id",
    "attempt_id",
    "invocation_id",
    "session_id",
    "request_id",
)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """The canonical execution ids in scope for the current task.

    Frozen because a context that could be mutated in place would change the
    meaning of log lines already emitted under it. `merged` returns a new one.
    """

    workspace_id: str = ""
    project_id: str = ""
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    session_id: str = ""
    request_id: str = ""

    def merged(self, **ids: str | None) -> ExecutionContext:
        """Return this context with the non-blank `ids` overlaid.

        Unknown names raise: a typo'd `noderun_id` would otherwise be accepted
        silently and correlate nothing, which is the failure this whole module
        exists to end.
        """
        unknown = sorted(set(ids) - set(FIELD_NAMES))
        if unknown:
            raise ValueError(
                f"not correlation ids: {', '.join(unknown)} (known: {', '.join(FIELD_NAMES)})"
            )
        overlay = {name: str(value) for name, value in ids.items() if value}
        if not overlay:
            return self
        return replace(self, **overlay)

    def as_log_fields(self) -> dict[str, str]:
        """Return the ids that are set, for merging onto a log event.

        Blank ids are omitted rather than rendered as `""`: a field that is
        present and empty reads as "this execution has no Run", which is a
        claim, while an absent field reads as "not recorded here", which is
        the truth.
        """
        return {f.name: value for f in fields(self) if (value := getattr(self, f.name))}

    def __bool__(self) -> bool:
        """True when any id is set — an all-blank context is falsy."""
        return any(getattr(self, f.name) for f in fields(self))


EMPTY = ExecutionContext()

_CONTEXT: ContextVar[ExecutionContext] = ContextVar(
    "maistro_execution_context",
    default=EMPTY,
)


def current_execution_context() -> ExecutionContext:
    """Return the context in scope, or the empty one when nothing is bound."""
    return _CONTEXT.get()


@contextlib.contextmanager
def bind_execution_context(**ids: str | None) -> Iterator[ExecutionContext]:
    """Bind `ids` onto the current context for the duration of the block.

    Additive and non-erasing: what the caller does not name it inherits, and a
    blank value it does name is ignored. Yields the resulting context so a
    caller that wants to log the ids it just bound need not read them back.
    """
    merged = _CONTEXT.get().merged(**ids)
    token = _CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _CONTEXT.reset(token)


def execution_context_processor(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog processor merging the active context onto every log event.

    `setdefault`, not assignment: a call site that passed `run_id=` explicitly
    knows something the ambient context does not — it is logging *about* another
    Run — and the ambient value must not overwrite it.
    """
    for name, value in current_execution_context().as_log_fields().items():
        event_dict.setdefault(name, value)
    return event_dict


@dataclass(frozen=True, slots=True)
class ExecutionProvenance:
    """Who produced a record: the Run, NodeRun and Attempt it came out of.

    A record's producer is a narrower question than the whole context — a
    learning does not care which HTTP request was in flight, it cares which
    execution taught it — so this is three fields rather than eight, and the
    stores that persist it carry three columns rather than eight (#709).
    """

    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""

    def __bool__(self) -> bool:
        """True when any id is set — a record produced outside any execution."""
        return bool(self.run_id or self.node_run_id or self.attempt_id)

    def as_columns(self) -> tuple[str | None, str | None, str | None]:
        """The three ids as a database row holds them: absent, not empty.

        `None` and not `""` because a provenance column holding an empty string
        reads as "produced by a Run whose id is empty", which is a claim, where
        NULL reads as "no execution was in scope" — what actually happened.

        Here rather than at each call site: six stores were each spelling the
        same `or None` three times, which is the same rule written in eighteen
        places and three extra branches per store for the complexity gate to
        notice. It noticed (#709).
        """
        return (self.run_id or None, self.node_run_id or None, self.attempt_id or None)


def observed_provenance(
    *,
    run_id: str = "",
    node_run_id: str = "",
    attempt_id: str = "",
) -> ExecutionProvenance:
    """Return a record's producer: what the caller named, else what is in scope.

    The same rule as `EventEnvelope.correlated`, and for the same reason: a
    caller recording a fact *about* another execution knows something the
    ambient context does not, so what it sets is never overwritten; a caller
    that simply did not think about it gets the truth for free.

    A record produced outside any execution comes back all-blank, and the
    stores write that as SQL NULL. An empty string in a provenance column
    would read as "produced by a Run with no id", which is a claim; absence
    reads as "no execution was in scope", which is what happened.
    """
    context = current_execution_context()
    return ExecutionProvenance(
        run_id=run_id or context.run_id,
        node_run_id=node_run_id or context.node_run_id,
        attempt_id=attempt_id or context.attempt_id,
    )
