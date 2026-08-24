"""What admitted a Run, named in one place.

A Run's `provenance[ADMISSION_SOURCE]` records the entry point that admitted
it. Three parts of the system need those names and none of them can import the
others: `runs.admission` writes the key, `runs.store` reads it to decide what
its retention bound may evict first, and each entry point supplies its own
value. A leaf module with no imports of its own is what lets all three agree on
the strings rather than on three copies of them.
"""

from __future__ import annotations

#: Provenance key recording how a Run entered the system.
ADMISSION_SOURCE = "admission_source"

#: `admission_source` for work that entered through the task queue.
TASK_QUEUE_SOURCE = "task_queue"

#: `admission_source` for work that entered as a chat turn.
CHAT_SOURCE = "chat"

#: `admission_source` for work a Schedule fired (#145).
SCHEDULE_SOURCE = "schedule"

#: Sources whose Runs a bounded store evicts *first*.
#:
#: Chat turns arrive orders of magnitude more often than task submissions, and
#: a task Run is the execution identity behind a receipt a caller still holds,
#: while a chat Run's job is to be followable for a while after its turn
#: (ADR-082326-c126). A source-agnostic bound would let the frequent kind evict
#: the durable kind, which is the specific cross-eviction the chat retention
#: policy exists to prevent — and it would do it inside `create_run`, before
#: any admitter's own sweep could run.
EPHEMERAL_ADMISSION_SOURCES = frozenset({CHAT_SOURCE})

#: Provenance keys a scheduled Run carries beyond its source (#145).
#:
#: Named here for the same reason the sources are: `scheduling.admission`
#: writes them and anything reading a Run's provenance has to agree on the
#: spelling without importing the scheduler.
SCHEDULE_ID_KEY = "schedule_id"

#: The occurrence a Run belongs to, not the moment its tick noticed it.
SCHEDULED_FOR_KEY = "scheduled_for"

#: True when the fire was a backfill after downtime rather than an on-time one.
#: The two mean different things and were previously indistinguishable.
SCHEDULE_CATCHUP_KEY = "catchup"

#: The Schedule's configured payload, carried onto the Run it fires.
#:
#: `Schedule.inputs` is what a parameterized schedule was set up to pass, and
#: instantiating its template alone dropped it — every such Run looked like one
#: configured with nothing. On the Run rather than only handed to a runner,
#: because a Run that cannot say what it was asked to do cannot be audited or
#: replayed.
SCHEDULE_INPUTS_KEY = "schedule_inputs"


def occurrence_key(provenance: dict[str, object] | None) -> tuple[str, str] | None:
    """The occurrence a scheduled Run claims, or None if it claims none.

    `(schedule_id, scheduled_for)` is the identity of a *firing* — the cursor
    never was (#220). A schedule's cursor says where enumeration resumes; two
    tickers reading it before either writes enumerate the same occurrences and
    both create Runs for them, and a crash between creating a Run and stamping
    the cursor re-enumerates the same occurrence on the next tick.

    `catchup` is deliberately **not** part of the key. A backfill and an
    on-time fire for the same nominal time are the same occurrence — that they
    were noticed at different moments is why the flag exists, not a reason to
    run the work twice.

    Both halves are required. A Run carrying one without the other is not a
    partial claim on anything; it is a Run that cannot say which firing it
    belongs to, and inventing a key for it would collide unrelated work.
    """
    if not provenance:
        return None
    schedule_id = provenance.get(SCHEDULE_ID_KEY)
    scheduled_for = provenance.get(SCHEDULED_FOR_KEY)
    if not (isinstance(schedule_id, str) and isinstance(scheduled_for, str)):
        return None
    if not (schedule_id and scheduled_for):
        return None
    return schedule_id, scheduled_for


__all__ = [
    "ADMISSION_SOURCE",
    "CHAT_SOURCE",
    "EPHEMERAL_ADMISSION_SOURCES",
    "SCHEDULED_FOR_KEY",
    "SCHEDULE_CATCHUP_KEY",
    "SCHEDULE_ID_KEY",
    "SCHEDULE_INPUTS_KEY",
    "SCHEDULE_SOURCE",
    "TASK_QUEUE_SOURCE",
    "occurrence_key",
]
