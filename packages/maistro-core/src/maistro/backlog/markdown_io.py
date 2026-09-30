"""Lossless Markdown import/export for the root backlog (#102).

Until the explicit authority cutover, root ``BACKLOG.md`` is the
hand-maintained work-source of record; afterwards the database is
authoritative and the file is generated documentation. Both directions are
exact, because a cutover that loses anything is not a migration:

**Parsing** walks the document as an ordered token stream — furniture lines
(everything that is not an item: title, legends, headings, section prose) and
item records. Furniture is kept verbatim so the renderer can replay it
byte-for-byte; item headers are parsed into structured fields (stable id,
title, status legend word, ``gap-*`` marker, milestone, the headings in force
at the item's position) and each item's body lines are kept verbatim,
including any header-suffix text (e.g. a trailing ``Blocked-by:`` annotation
after the closing ``**``).

**Rendering** is the inverse and is deterministic: given the same furniture
and the same item state it produces the same bytes, every time, with no clock
and no locale in the output. A generated ``BACKLOG.md`` embeds nothing that
would make two exports of one database state differ.

**Dependencies** are the structured projection of the document's
``blocked-by`` annotations. Three written forms are recognised, in item bodies
and header suffixes alike:

- ``- Blocked-by: ``engine-001```` (the canonical legend form);
- prose such as ``Blocked-by 010/011/012`` — bare numbers resolve within the
  item's own id prefix;
- ``Depends on `[engine-030]```.

Everything else in a body is prose and is never reinterpreted.

The graph is validated at import: every dependency must name an item in the
document, and the dependency graph must be acyclic — the database refuses to
hold a backlog whose blocked-by edges are lies.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from maistro.backlog.model import BacklogItem, BacklogItemStatus

#: `**[engine-001] Title — Status[; `gap-x`] — milestone**`, with the id allowing
#: the `[turing-030..034]` range form used for a batch of sibling items. Same
#: grammar as ``scripts/check-backlog-consistency.py`` — one language, two
#: readers — with the remainder of the line (header suffix) captured too.
_ITEM = re.compile(
    r"^\*\*\[(?P<prefix>[a-z]+)-(?P<number>\d+(?:\.\.\d+)?)\]\s+"
    r"(?P<title>.+?)\s+—\s+(?P<state>[^—*]+?)\s*(?:—\s*(?P<milestone>[^*]+?))?\*\*"
    r"(?P<suffix>.*)$"
)
_ITEM_LINE = re.compile(r"^\*\*\[[a-z]+-\d")

#: Dependency annotations, matched case-insensitively against body text.
_DEP_MARKER = re.compile(r"\b(?:blocked-by|blocked by|depends on)\b\s*:?", re.IGNORECASE)
#: One dependency reference: ``[engine-030]``, ``engine-030``, or ``030`` (with
#: the bare-number form resolved against the referencing item's prefix).
_DEP_REF = re.compile(r"`?\[?([a-z]+-)?(\d+(?:\.\.\d+)?)\]?`?")

#: Statuses that mean "closed" in the Markdown vocabulary, mapped onto the
#: structured terminal statuses. Everything else is open/blocked state.
_TERMINAL_STATUS_WORDS: Mapping[str, BacklogItemStatus] = {
    "Implemented": BacklogItemStatus.DONE,
    "Abandoned": BacklogItemStatus.REJECTED,
    "Obsolete": BacklogItemStatus.REJECTED,
    "Superseded": BacklogItemStatus.REJECTED,
}
_BLOCKED_STATUS_WORD = "Blocked"

FURNITURE = "furniture"
ITEM = "item"


class MarkdownBacklogError(ValueError):
    """The document cannot be imported as written; the message says what to fix."""


@dataclass(frozen=True)
class ParsedItem:
    """One backlog item as written: structured header plus verbatim body."""

    item_id: str
    title: str
    status_word: str
    gap_marker: str | None
    milestone_text: str | None
    #: The ``## `` heading in force at the item's position.
    section: str
    #: The ``### `` heading in force at the item's position, if any.
    subsection: str | None
    #: Text after the closing ``**`` on the header line, if any (e.g. a
    #: trailing "Blocked-by" annotation).
    header_suffix: str
    #: Non-header lines of the item, verbatim, in document order.
    body: tuple[str, ...]
    #: Stable ids this item is blocked by, parsed from its annotations.
    dependencies: tuple[str, ...]

    def written_block(self) -> str:
        """The item exactly as written: header line plus verbatim body."""
        header = f"**[{self.item_id}] {self.title} — {self.status_word}"
        if self.gap_marker:
            header += f"; `{self.gap_marker}`"
        if self.milestone_text:
            header += f" — {self.milestone_text}"
        header += "**"
        if self.header_suffix:
            header += self.header_suffix
        return "\n".join((header, *self.body))


@dataclass(frozen=True)
class ParsedDocument:
    """A parsed backlog: ordered token stream plus the structured items.

    ``tokens`` is the whole document — furniture lines verbatim and one item
    marker per item, in document order. It is the unit the document state
    persists, so an export after a restart replays the same structure without
    the original file.
    """

    tokens: tuple[tuple[str, str], ...]
    items: tuple[ParsedItem, ...]

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.items)


def _split_state(state: str) -> tuple[str, str | None]:
    """`Accepted; `gap-impl`` -> ("Accepted", "gap-impl")."""
    status, _, gap = state.partition(";")
    marker = gap.strip().strip("`").strip()
    return status.strip(), (marker or None)


def _resolve_dep(token: str, own_prefix: str) -> str | None:
    """Resolve one dependency reference to an item id, or ``None`` for prose.

    ``engine-030`` and ``[engine-030]`` name the id directly; a bare ``030``
    is a sibling reference and resolves within the referencing item's prefix.
    The resolver is shape-first: anything the reference grammar cannot read
    (prose fragments around the marker) is ignored rather than guessed.
    Membership in the document is the caller's check (validation), not ours.
    """
    match = _DEP_REF.fullmatch(token.strip().strip(",.;"))
    if match is None:
        return None
    prefix, number = match.group(1), match.group(2)
    candidate = prefix.rstrip("-") + "-" + number if prefix else f"{own_prefix}-{number}"
    return candidate


def parse_dependency_candidates(item: ParsedItem) -> tuple[str, ...]:
    """Every ``blocked-by`` reference the item's annotations name, resolved.

    Unlike :func:`parse_dependencies` this does not filter to ids the
    document defines -- validation needs the unresolved ones so it can
    refuse the document honestly instead of silently dropping the edge.
    """
    deps: list[str] = []
    own_prefix = item.item_id.rsplit("-", 1)[0]
    lines = (item.header_suffix, *item.body) if item.header_suffix else item.body
    for line in lines:
        position = 0
        while (marker := _DEP_MARKER.search(line, position)) is not None:
            rest = line[marker.end() :]
            # The annotation ends at the next sentence boundary; references
            # are read out of that span only.
            span = re.split(r"(?<=\w)[.;](?:\s|$)", rest, maxsplit=1)[0]
            for token in span.split():
                # One token may pack several references: "010/011/012" or
                # "010,011". Split the separators before resolving.
                for part in re.split(r"[/,]+", token):
                    resolved = _resolve_dep(part, own_prefix)
                    if resolved is not None and resolved != item.item_id and resolved not in deps:
                        deps.append(resolved)
            position = marker.end()
    return tuple(deps)


def parse_dependencies(item: ParsedItem, known: set[str]) -> tuple[str, ...]:
    """The item's structured dependency projection: ids the document defines.

    Only text at a dependency marker counts, so a ``Depends on`` annotation
    resolves while ordinary prose mentioning ``[engine-094]`` does not
    invent a dependency. References to ids the document never defines are
    validation failures (:func:`validate_document`), never silent drops.
    """
    return tuple(dep for dep in parse_dependency_candidates(item) if dep in known)


def parse_markdown(text: str) -> ParsedDocument:
    """Parse a backlog document into its token stream and structured items.

    Raises :class:`MarkdownBacklogError` on a malformed item header or a
    duplicate id — the same honesty the consistency gate applies to the file,
    applied to whatever text is about to become the authority.
    """
    tokens: list[tuple[str, str]] = []
    items: list[ParsedItem] = []
    seen: set[str] = set()
    section = ""
    subsection: str | None = None
    body_lines: list[str] | None = None
    header: ParsedItem | None = None

    for line in text.splitlines():
        if _ITEM_LINE.match(line) is None:
            if body_lines is not None:
                body_lines.append(line)
                continue
            tokens.append((FURNITURE, line))
            if line.startswith("## "):
                section = line[3:].strip()
                subsection = None
            elif line.startswith("### "):
                subsection = line[4:].strip()
            continue
        match = _ITEM.match(line)
        if match is None:
            raise MarkdownBacklogError(f"unparsable item header: {line[:80]}")
        if body_lines is not None and header is not None:
            items.append(_finish(header, body_lines))
        item_id = f"{match.group('prefix')}-{match.group('number')}"
        if item_id in seen:
            raise MarkdownBacklogError(f"{item_id}: duplicate item id")
        seen.add(item_id)
        status_word, gap_marker = _split_state(match.group("state"))
        suffix = match.group("suffix")
        body_lines = []
        header = ParsedItem(
            item_id=item_id,
            title=match.group("title"),
            status_word=status_word,
            gap_marker=gap_marker,
            milestone_text=(match.group("milestone") or "").strip() or None,
            section=section,
            subsection=subsection,
            header_suffix=suffix,
            body=(),
            dependencies=(),
        )
        tokens.append((ITEM, item_id))

    if body_lines is not None and header is not None:
        items.append(_finish(header, body_lines))

    return ParsedDocument(tokens=tuple(tokens), items=tuple(items))


def _finish(header: ParsedItem, body_lines: list[str]) -> ParsedItem:
    """Rebuild ``header`` with its verbatim body lines."""
    return ParsedItem(
        item_id=header.item_id,
        title=header.title,
        status_word=header.status_word,
        gap_marker=header.gap_marker,
        milestone_text=header.milestone_text,
        section=header.section,
        subsection=header.subsection,
        header_suffix=header.header_suffix,
        body=tuple(body_lines),
        dependencies=(),
    )


def validate_document(document: ParsedDocument) -> None:
    """Refuse a document whose dependency graph is not honest.

    Every ``blocked-by`` must name an item in the same document, and the graph
    must be acyclic: importing a backlog whose edges point nowhere (or in a
    loop) would launder a broken graph into structured state.
    """
    known = set(document.item_ids)
    edges: dict[str, tuple[str, ...]] = {}
    for item in document.items:
        candidates = parse_dependency_candidates(item)
        for dep in candidates:
            if dep not in known:
                raise MarkdownBacklogError(
                    f"{item.item_id}: blocked-by names {dep!r}, which is not in the document"
                )
        edges[item.item_id] = candidates
    _require_acyclic(edges)


def _require_acyclic(edges: Mapping[str, tuple[str, ...]]) -> None:
    state: dict[str, int] = {}  # 0 = visiting, 1 = done; absent = unvisited

    def walk(node: str, path: list[str]) -> None:
        mark = state.get(node)
        if mark == 0:
            cycle = [*path[path.index(node) :], node]
            raise MarkdownBacklogError("blocked-by cycle: " + " -> ".join(cycle))
        if mark == 1:
            return
        state[node] = 0
        for dep in edges.get(node, ()):
            walk(dep, [*path, node])
        state[node] = 1

    for node in edges:
        walk(node, [])


def render_item(item: BacklogItem) -> str:
    """Render one item's full written block (header + body), deterministically.

    Imported items replay their stored origin verbatim — the round-trip
    contract; natively-created database items are rendered in the same
    grammar from their structured fields.
    """
    lines = [_render_header(item)]
    lines.extend(item.origin.body if item.origin is not None else _prose_body(item))
    return "\n".join(lines)


def _render_header(item: BacklogItem) -> str:
    origin = item.origin
    if origin is not None:
        status = origin.status_word
        if origin.gap_marker:
            status += f"; `{origin.gap_marker}`"
        header = f"**[{item.item_id}] {item.title} — {status}"
        if origin.milestone_text:
            header += f" — {origin.milestone_text}"
        header += "**"
        if origin.header_suffix:
            header += origin.header_suffix
        return header
    status = _STATUS_WORD_BY_STATUS[item.status]
    header = f"**[{item.item_id}] {item.title} — {status}"
    if item.milestone:
        header += f" — {item.milestone}"
    return header + "**"


#: Deterministic vocabulary for items that were born in the database: the
#: legend word each structured status renders as. Imported items keep the
#: word they were written with (``BacklogOrigin.status_word``).
_STATUS_WORD_BY_STATUS: Mapping[BacklogItemStatus, str] = {
    BacklogItemStatus.OPEN: "Proposed",
    BacklogItemStatus.IN_PROGRESS: "Accepted",
    BacklogItemStatus.BLOCKED: "Blocked",
    BacklogItemStatus.DONE: "Implemented",
    BacklogItemStatus.REJECTED: "Abandoned",
}


def _prose_body(item: BacklogItem) -> list[str]:
    """Body lines for a database-native item, from its structured fields."""
    lines: list[str] = []
    if item.dependencies:
        refs = ", ".join(f"`{dep}`" for dep in item.dependencies)
        lines.append(f"- Blocked-by: {refs}")
    if item.details:
        lines.extend(f"- {line}" for line in item.details.splitlines())
    if item.status.is_terminal and item.closure is not None:
        refs = ", ".join(f"`{ref}`" for ref in item.closure.evidence_refs)
        lines.append(f"- Evidence: {item.closure.summary} ({refs})")
    return lines


def render_document(
    tokens: Sequence[tuple[str, str]],
    items: Mapping[str, BacklogItem],
) -> str:
    """Render the whole document from its token stream and item state.

    Deterministic by construction: tokens replay in order, furniture verbatim,
    items through :func:`render_item`, and the join uses exactly the line
    endings the input carried.
    """
    lines: list[str] = []
    for kind, value in tokens:
        if kind == FURNITURE:
            lines.append(value)
        else:
            item = items.get(value)
            if item is None:
                raise MarkdownBacklogError(f"cannot render {value}: not in the store")
            lines.append(render_item(item))
    return "\n".join(lines) + "\n"


def status_to_structured(status_word: str) -> BacklogItemStatus:
    """Map a Markdown status legend word onto the structured status."""
    if status_word == _BLOCKED_STATUS_WORD:
        return BacklogItemStatus.BLOCKED
    terminal = _TERMINAL_STATUS_WORDS.get(status_word)
    if terminal is not None:
        return terminal
    return BacklogItemStatus.OPEN


def is_terminal_word(status_word: str) -> bool:
    """Whether the legend word means the item is closed."""
    return status_word in _TERMINAL_STATUS_WORDS


__all__ = [
    "FURNITURE",
    "ITEM",
    "MarkdownBacklogError",
    "ParsedDocument",
    "ParsedItem",
    "is_terminal_word",
    "parse_dependencies",
    "parse_dependency_candidates",
    "parse_markdown",
    "render_document",
    "render_item",
    "status_to_structured",
    "validate_document",
]
