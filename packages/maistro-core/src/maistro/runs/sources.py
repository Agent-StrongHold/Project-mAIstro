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

__all__ = [
    "ADMISSION_SOURCE",
    "CHAT_SOURCE",
    "EPHEMERAL_ADMISSION_SOURCES",
    "TASK_QUEUE_SOURCE",
]
