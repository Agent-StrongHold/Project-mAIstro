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

#: What kind of firing produced the Run: a nominal recurrence or a manual fire.
#:
#: A manual fire (#1120) is a deliberate user action, not a cron occurrence, and
#: a Run that looks exactly like a scheduled tick erases the difference — which
#: matters for audit ("why did this run outside its cron window?") and for
#: semantics (a manual fire must not be mistaken for a nominal one when reading
#: `scheduled_for`). Both kinds carry the key, so its absence means the Run
#: predates the distinction rather than that it was fired by either.
SCHEDULE_TRIGGER_KEY = "schedule_trigger"

#: `schedule_trigger` for a Run a recurring evaluation fired.
SCHEDULE_TRIGGER_RECURRING = "recurring"

#: `schedule_trigger` for a Run a caller asked for by hand (#1120).
SCHEDULE_TRIGGER_MANUAL = "manual"

#: The manual fire's stable occurrence identity token (#1120).
#:
#: A nominal occurrence is identified by its cron time, and `(schedule_id,
#: scheduled_for)` claims it. A manual fire has no cron time — minting a fresh
#: `datetime.now()` per request makes the identity different on every retry,
#: which is exactly how a double submit becomes two Runs. So a manual fire
#: claims `(schedule_id, schedule_fire_id)` instead: an opaque token the caller
#: keeps stable across retries of the same logical request (and the server
#: mints when the caller does not supply one, making each request its own
#: deliberate firing). Opaque, not a timestamp, on purpose — it is an identity,
#: not an instant; the instant a fire was requested stays in `scheduled_for`.
SCHEDULE_FIRE_ID_KEY = "schedule_fire_id"

#: Namespace separating a manual fire's claim from a nominal occurrence's.
#:
#: Both claims live in one index as `(schedule_id, token)`. The prefix is what
#: keeps a caller who passes `schedule_fire_id` equal to some cron time's ISO
#: string from claiming that nominal occurrence — the two identity spaces never
#: intersect, so a manual fire can never consume a scheduled tick's slot.
MANUAL_OCCURRENCE_PREFIX = "manual:"


def occurrence_key(provenance: dict[str, object] | None) -> tuple[str, str] | None:
    """The occurrence a scheduled Run claims, or None if it claims none.

    A nominal occurrence claims `(schedule_id, scheduled_for)` — the identity
    of a *firing* — the cursor never was (#220). A schedule's cursor says where
    enumeration resumes; two tickers reading it before either write enumerate
    the same occurrences and both create Runs for them, and a crash between
    creating a Run and stamping the cursor re-enumerates the same occurrence on
    the next tick.

    A manual fire claims `(schedule_id, "manual:" + fire_id)` instead (#1120).
    Its identity is the caller's stable request token, not an instant: minting
    `datetime.now()` per request is how a retried click became a second Run.
    The prefix keeps the two identity spaces disjoint, so a manual token can
    never collide with — and thereby consume — a nominal occurrence's slot.

    `catchup` is deliberately **not** part of either key. A backfill and an
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
    if not isinstance(schedule_id, str) or not schedule_id:
        return None
    fire_id = provenance.get(SCHEDULE_FIRE_ID_KEY)
    if isinstance(fire_id, str) and fire_id:
        return schedule_id, f"{MANUAL_OCCURRENCE_PREFIX}{fire_id}"
    scheduled_for = provenance.get(SCHEDULED_FOR_KEY)
    if not isinstance(scheduled_for, str) or not scheduled_for:
        return None
    return schedule_id, scheduled_for


__all__ = [
    "ADMISSION_SOURCE",
    "CHAT_SOURCE",
    "EPHEMERAL_ADMISSION_SOURCES",
    "MANUAL_OCCURRENCE_PREFIX",
    "SCHEDULED_FOR_KEY",
    "SCHEDULE_CATCHUP_KEY",
    "SCHEDULE_FIRE_ID_KEY",
    "SCHEDULE_ID_KEY",
    "SCHEDULE_INPUTS_KEY",
    "SCHEDULE_SOURCE",
    "SCHEDULE_TRIGGER_KEY",
    "SCHEDULE_TRIGGER_MANUAL",
    "SCHEDULE_TRIGGER_RECURRING",
    "TASK_QUEUE_SOURCE",
    "occurrence_key",
]
