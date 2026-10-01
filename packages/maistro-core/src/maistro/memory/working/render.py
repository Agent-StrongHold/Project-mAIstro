"""The GUIDE and WORKING prompt representations of working memory (#301).

Two renderings of the same projection, for two different jobs:

* **WORKING** — the active set inline: survival-set entries first (they are
  the memories the system must not forget, ADR-091's always-include band),
  then the rest of the working set newest-first, whole entries only, packed
  to the token budget. No fragments: a half-line of an observation is not a
  smaller observation, it is a misquotation.
* **GUIDE** — the index of what exists beyond the working set: every
  addressable full result with its id, source, digest and first line, plus
  the recall invocation that fetches it. This is "log-as-context" without
  paying for payloads: the model sees that a full result exists, where it is
  addressed, and asks for it by reference.

Both renderings are deterministic — same projection, same bytes — because a
prompt representation that shifts between otherwise identical turns breaks
KV-cache reuse for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.memory.working.projection import WorkspaceWorkingMemory
from maistro.memory.working.types import ObservationKind, WorkspaceObservation

_CHARS_PER_TOKEN = 4

#: Survival-set entries render first and never drop for budget.
_WORKING_HEADER = "# WORKING MEMORY (active set)"
_GUIDE_HEADER = "# WORKING MEMORY GUIDE (addressable results)"
_GUIDE_FOOTER = (
    "Full results are stored once and addressed by id; "
    'recall the id (e.g. recall("res-…")) to read one in full.'
)


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def _short_digest(digest: str) -> str:
    return digest[:12] if digest else "-"


def _entry_line(entry: WorkspaceObservation) -> str:
    pinned = " *pinned*" if entry.survive_reset else ""
    ref = f" ref={entry.result_ref}" if entry.result_ref else ""
    return f"- [c{entry.cycle} {entry.kind.value}{pinned}] {entry.text}{ref}"


def _guide_line(entry: WorkspaceObservation, size_hint: int) -> str:
    if entry.result_ref:
        first_line = entry.text.splitlines()[0] if entry.text else ""
        return (
            f"- {entry.result_ref} · {entry.run_id or 'run?'} · c{entry.cycle} · "
            f"digest {_short_digest(entry.digest)} · ~{size_hint}B · “{first_line}”"
        )
    return (
        f"- log:{entry.entry_id} · {entry.kind.value} · c{entry.cycle} · "
        f"digest {_short_digest(entry.digest)} · “{entry.text}”"
    )


def _pack_lines(lines: list[str], budget_tokens: int | None) -> list[str]:
    """Whole lines until the budget is spent. ``None`` means unbounded."""
    if budget_tokens is None:
        return lines
    kept: list[str] = []
    spent = 1 + _estimate_tokens(_WORKING_HEADER)
    for line in lines:
        cost = _estimate_tokens(line) + 1
        if spent + cost > budget_tokens:
            continue
        kept.append(line)
        spent += cost
    return kept


@dataclass(frozen=True)
class RenderedWorkingContext:
    """Both prompt blocks plus what they cost and carried."""

    working: str
    guide: str
    entries_rendered: int
    results_listed: int
    pinned_rendered: int
    tokens_spent: int


def render_working(
    entries: list[WorkspaceObservation],
    *,
    budget_tokens: int | None = None,
) -> str:
    """The WORKING block: survival entries first, then newest-first.

    ``budget_tokens`` drops whole entries in order — it never truncates one,
    and it never drops a survival-set entry: that is the one promise the
    survival set makes, and a budget is not allowed to break it silently.
    """
    pinned = [e for e in entries if e.survive_reset]
    rest = [e for e in entries if not e.survive_reset]
    rest.reverse()  # newest first for the un-pinned tail
    pinned_lines = [_entry_line(e) for e in pinned]
    spent = (
        1
        + _estimate_tokens(_WORKING_HEADER)
        + sum(_estimate_tokens(line) + 1 for line in pinned_lines)
    )
    rest_lines: list[str] = []
    for entry in rest:
        line = _entry_line(entry)
        cost = _estimate_tokens(line) + 1
        if budget_tokens is not None and spent + cost > budget_tokens:
            continue
        rest_lines.append(line)
        spent += cost
    body = pinned_lines + rest_lines
    if not body:
        return ""
    return "\n".join([_WORKING_HEADER, *body])


def render_guide(
    entries: list[WorkspaceObservation],
    sizes: dict[str, int] | None = None,
    *,
    budget_tokens: int | None = None,
) -> str:
    """The GUIDE block: what exists, addressed, one line each.

    ``sizes`` maps result ids to payload byte sizes when known, so the guide
    can hint at cost before the model pays it.
    """
    sizes = sizes or {}
    addressed = [e for e in entries if e.result_ref]
    log_only = [e for e in entries if not e.result_ref and e.kind is not ObservationKind.SUMMARY]
    lines = [_guide_line(e, sizes.get(e.result_ref or "", 0)) for e in addressed]
    lines += [_guide_line(e, 0) for e in log_only]
    lines = _pack_lines(lines, budget_tokens)
    if not lines:
        return ""
    return "\n".join([_GUIDE_HEADER, *lines, _GUIDE_FOOTER])


def render_working_context(
    projection: WorkspaceWorkingMemory,
    *,
    working_budget_tokens: int | None = None,
    guide_budget_tokens: int | None = None,
) -> RenderedWorkingContext:
    """Render both representations from one projection.

    WORKING is packed first (it is the active set — the point of the
    feature), GUIDE gets whatever budget remains named for it. Survival
    entries are in WORKING by construction; the GUIDE block deliberately
    lists *all* addressable results, including ones whose entries the
    working set has folded — the log remembers them even when the working
    set does not, and the reference is how the model gets them back.
    """
    active = projection.active_entries()
    working_text = render_working(active, budget_tokens=working_budget_tokens)
    everything = projection.all_entries()
    sizes = {
        result.result_id: len(result.content.encode("utf-8")) for result in projection.all_results()
    }
    guide_text = render_guide(everything, sizes, budget_tokens=guide_budget_tokens)
    entries_rendered = sum(1 for line in working_text.splitlines() if line.startswith("- "))
    pinned_rendered = sum(1 for line in working_text.splitlines() if "*pinned*" in line)
    results_listed = sum(1 for line in guide_text.splitlines() if line.startswith("- "))
    return RenderedWorkingContext(
        working=working_text,
        guide=guide_text,
        entries_rendered=max(entries_rendered, 0),
        results_listed=results_listed,
        pinned_rendered=pinned_rendered,
        tokens_spent=_estimate_tokens(working_text) + _estimate_tokens(guide_text),
    )
