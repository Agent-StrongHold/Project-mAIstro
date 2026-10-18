"""Working-memory types for the per-Workspace projection (M4-H, #301).

Implements the durable half of ADR-082226-5104's working memory: an
**append-only** per-Workspace observation/tool log whose full results are
**reference-addressable** (stored once, addressed by id, never inlined into
prompt text), plus the marker entries (cycle summaries, hard resets) that make
the working set a *derivation* over the log instead of a second mutable copy.

Two invariants are the reason this module exists:

* **The log is lossless.** Entries are never updated or deleted; simplification
  and hard resets *append* markers that change what the working-set derivation
  returns, so the full history stays retrievable through
  ``WorkspaceLogStore.list_entries`` after any number of resets.
* **Full results live behind references.** A log entry carries a compact
  ``text`` line and a ``result_ref``; the full payload is a
  :class:`WorkingResult` fetched by that reference. Prompt assembly renders the
  compact line and offers the reference (the GUIDE representation), so the
  context window never pays for payloads the current turn has not asked for.

``ObservationKind.RESET`` and ``ObservationKind.SUMMARY`` entries are written by
:mod:`maistro.memory.working.simplify`; ``HYPOTHESIS`` entries are the
tentative kind ADR-082226-5104 §6 says working memory may hold that durable
memory should not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ObservationKind(StrEnum):
    """What kind of thing an append-only log entry records."""

    #: Something a Run saw or did, in one compact line.
    OBSERVATION = "observation"
    #: A pointer to a full tool result behind ``result_ref``.
    TOOL_RESULT = "tool_result"
    #: A tentative claim — working memory may hold speculation durable memory
    #: should not (ADR-082226-5104 §6). Measured for redundancy, never
    #: promoted by this module.
    HYPOTHESIS = "hypothesis"
    #: A rolled summary that *folds* earlier entries (see ``meta["folds"]``).
    SUMMARY = "summary"
    #: A hard-reset marker naming its survival set (see ``meta["survival"]``).
    RESET = "reset"


def content_digest(content: str) -> str:
    """Stable content digest used for reference-addressing and dedup."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_entry_id() -> str:
    return f"obs-{uuid4().hex[:20]}"


def make_result_id(workspace_id: str, source: str, content: str) -> str:
    """Content-address a result within its Workspace.

    The Workspace is mixed in so the same payload observed in two Workspaces is
    two records (physical isolation, ADR-082226-5104 §5), while the same
    payload recorded twice *inside* one Workspace is one record — identical
    results are stored once and referenced twice.
    """
    material = f"{workspace_id}\x00{source}\x00{content}"
    return "res-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class WorkingResult:
    """A full, reference-addressable result (tool output, fetched document...).

    Stored once under ``result_id``; log entries point at it through
    ``WorkspaceObservation.result_ref``. The record is the *only* place the
    full payload exists — losing the results table would lose payloads, which
    is why the durable twin stores it and the ephemeral projection only
    hydrates what active entries reference.
    """

    workspace_id: str
    result_id: str
    source: str
    content: str
    created_at: datetime = field(default_factory=_utcnow)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        return content_digest(self.content)

    def to_json(self) -> str:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["kind"] = None  # reserved; keeps the payload shape explicit
        payload.pop("digest", None)
        return json.dumps(payload, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> WorkingResult:
        payload = json.loads(raw)
        payload.pop("kind", None)
        payload["created_at"] = datetime.fromisoformat(str(payload["created_at"]))
        return cls(**payload)


@dataclass(frozen=True)
class WorkspaceObservation:
    """One append-only log entry: a compact line, never the full payload."""

    workspace_id: str
    entry_id: str
    kind: ObservationKind
    cycle: int
    text: str
    run_id: str = ""
    #: Address of the full result behind this entry, when one exists.
    result_ref: str | None = None
    #: Digest of the *observed content* (entry text, or the referenced
    #: result's content when ``result_ref`` is set). Equal digests are how
    #: redundant hypotheses are recognised without any vector retrieval.
    digest: str = ""
    #: Members of the implicit survival set: kept in the working set across
    #: simplification folds and hard resets.
    survive_reset: bool = False
    #: Log position. Assigned by the store on ``append``; ``None`` only for a
    #: not-yet-appended entry.
    seq: int | None = None
    created_at: datetime = field(default_factory=_utcnow)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["kind"] = self.kind.value
        return json.dumps(payload, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> WorkspaceObservation:
        payload = json.loads(raw)
        payload["kind"] = ObservationKind(str(payload["kind"]))
        payload["created_at"] = datetime.fromisoformat(str(payload["created_at"]))
        return cls(**payload)


def observation(
    *,
    workspace_id: str,
    cycle: int,
    text: str,
    kind: ObservationKind = ObservationKind.OBSERVATION,
    run_id: str = "",
    result_ref: str | None = None,
    digest: str | None = None,
    survive_reset: bool = False,
    meta: dict[str, Any] | None = None,
) -> WorkspaceObservation:
    """Build a log entry, defaulting its digest from the content it carries.

    The digest defaults to the referenced result's digest when ``result_ref``
    is given (callers pass it explicitly), else the digest of ``text`` — so
    two hypotheses with the same text collide in ``by_digest`` without any
    embedding or similarity model.
    """
    return WorkspaceObservation(
        workspace_id=workspace_id,
        entry_id=make_entry_id(),
        kind=kind,
        cycle=cycle,
        text=text,
        run_id=run_id,
        result_ref=result_ref,
        digest=digest if digest is not None else content_digest(text),
        survive_reset=survive_reset,
        meta=meta if meta is not None else {},
    )


def summary_entry(
    *,
    workspace_id: str,
    cycle: int,
    folded_ids: list[str],
    text: str,
    through_cycle: int | None = None,
    run_id: str = "",
    survive_reset: bool = False,
) -> WorkspaceObservation:
    """A rolled summary that folds the named entries out of the working set.

    ``meta["folds"]`` is the derivation input: an entry is outside the working
    set when a *later* summary folds it. The folded entries stay in the log.
    """
    return observation(
        workspace_id=workspace_id,
        cycle=cycle,
        kind=ObservationKind.SUMMARY,
        text=text,
        run_id=run_id,
        survive_reset=survive_reset,
        meta={
            "folds": list(folded_ids),
            "through_cycle": through_cycle if through_cycle is not None else cycle,
        },
    )


def reset_entry(
    *,
    workspace_id: str,
    cycle: int,
    survival_ids: list[str],
    run_id: str = "",
) -> WorkspaceObservation:
    """A hard-reset marker naming the explicit survival set it keeps.

    Everything at or before this marker's log position leaves the working set
    except the survival set (the ids named here plus every entry flagged
    ``survive_reset``). The marker is itself the record of the reset: what was
    dropped, when, by which run, is readable forever.
    """
    return observation(
        workspace_id=workspace_id,
        cycle=cycle,
        kind=ObservationKind.RESET,
        text=f"hard reset; survival set: {len(survival_ids)} entr(y/ies)",
        run_id=run_id,
        survive_reset=False,
        meta={"survival": list(survival_ids)},
    )
