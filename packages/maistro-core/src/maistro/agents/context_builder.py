"""Context builder: assembles prompt from soul + tools + learnings + episodic.

Order matters: soul -> tool prompts -> promoted learnings -> matched learnings -> episodic memories.
Token budget enforcement prevents context overflow -- learnings are dropped (lowest priority first)
before soul prompt, which is never truncated.

The episodic half of that sentence was aspirational until #622: this module
named episodic memory in its own docstring and contained no code that read any.
It now calls the `ContextAssemblyPolicy` the container has always built and
nothing has ever read, which is what made that policy's ADR-091 layer rules
reachable at all.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from maistro.protocols.memory import ContextAssemblyPolicy, LearningStore
    from maistro.protocols.prompts import PromptManager
    from maistro.types.agent import AgentIdentity

logger = logging.getLogger("maistro.context_builder")

_LEARNINGS_BOUNDARY = "<maistro:corrections"

_CHARS_PER_TOKEN = 4

_DEFAULT_SYSTEM_TOKEN_BUDGET = 4096


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


_MAISTRO_TAG_RE = re.compile(r"<\s*/?\s*maistro:[A-Za-z0-9_.:-]*\s*[^>]*>", re.IGNORECASE)


def _neutralize_delimiters(text: str) -> str:
    """Strip any `<maistro:...>` tag from learning text before interpolation.

    Learnings are model-authored and are interpolated into the *system* prompt
    between `<maistro:corrections>` delimiters. A learning containing the
    closing tag terminates the block early, so everything after it reads as
    top-level system instruction rather than as a correction — a stored prompt
    injection that survives across sessions, since learnings persist and are
    re-injected. The delimiter is the trust boundary, so nothing that could be
    mistaken for one may cross it.

    Any `maistro:` tag is removed, opening or closing, not just the exact
    footer: `<maistro:corrections type="x">` opens a second block just as
    effectively as `</maistro:corrections>` closes the first one, and matching
    only the literal footer would leave that half open. Whitespace and
    attribute variants are covered because a parser-shaped filter that only
    catches the canonical spelling is not a filter.

    Whitespace is permitted on *both* sides of the optional slash. The consumer
    is a delimiter-tolerant language model, not an XML parser, so if
    `</ maistro:corrections>` has to be treated as a delimiter then so does
    `< /maistro:corrections>`; anchoring the slash to `<` left the second form
    matching nothing and preserved the stored prompt-escape it was written to
    remove.
    """
    return _MAISTRO_TAG_RE.sub("", text)


def _render_learnings_block(
    learnings: list[Any],
    *,
    block_type: str,
    budget_chars: int,
    use_rca_prefix: bool,
) -> tuple[str | None, list[int], int]:
    """Render a ``<maistro:corrections>`` block within ``budget_chars``.

    Returns ``(block_text_or_None, kept_ids, added_count)``. ``block_text`` is
    ``None`` when nothing fit within the budget.
    """
    header = f'<maistro:corrections type="{block_type}">'
    footer = "</maistro:corrections>"
    overhead = len(header) + len(footer) + 2
    lines: list[str] = [header]
    used = overhead
    kept_ids: list[int] = []
    added = 0
    for lr in learnings:
        # Sanitize before measuring, so the budget reflects what is actually
        # emitted and a long tag cannot be counted then dropped.
        raw_category = lr.rca_category or ""
        prefix = (
            f"[{_neutralize_delimiters(raw_category)}] " if use_rca_prefix and raw_category else ""
        )
        entry = f"- {prefix}{_neutralize_delimiters(lr.learning)}"
        if used + len(entry) + 1 > budget_chars:
            break
        lines.append(entry)
        used += len(entry) + 1
        added += 1
        if lr.id is not None:
            kept_ids.append(lr.id)
    if added == 0:
        return None, [], 0
    lines.append(footer)
    return "\n".join(lines), kept_ids, added


class ContextBuilder:
    """Assembles the full prompt context for an agent."""

    async def build(
        self,
        messages: list[dict[str, Any]],
        identity: AgentIdentity,
        *,
        prompt_manager: PromptManager,
        learning_store: LearningStore | None = None,
        context_assembly_policy: ContextAssemblyPolicy | None = None,
        agent_id: str = "",
        user_id: str = "",
        org_id: str = "",
        team_id: str = "",
        project_id: str = "",
        run_id: str = "",
        session_id: str = "",
        system_token_budget: int = _DEFAULT_SYSTEM_TOKEN_BUDGET,
        enable_cache_breakpoints: bool = False,
    ) -> tuple[list[dict[str, Any]], list[int]]:
        system_parts: list[str] = []
        budget_chars = system_token_budget * _CHARS_PER_TOKEN
        kept_ids: list[int] = []

        soul_name = identity.soul_prompt_name or f"agent.{identity.name}.soul"
        soul = await prompt_manager.get(soul_name)
        if soul:
            system_parts.append(soul)
            budget_chars -= len(soul)
            if budget_chars < 0:
                logger.warning(
                    "Soul prompt exceeds token budget: soul=%d chars, budget=%d tokens. "
                    "Learnings will be dropped.",
                    len(soul),
                    system_token_budget,
                )

        if learning_store and identity.memory_config.get("learnings") and budget_chars > 0:
            promoted = await learning_store.get_promoted(org_id=org_id)
            budget_chars = _apply_learnings(
                promoted,
                kind="promoted",
                use_rca_prefix=True,
                budget_chars=budget_chars,
                system_parts=system_parts,
                kept_ids=kept_ids,
            )

        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = str(msg.get("content", ""))
                break

        if (
            learning_store
            and user_text
            and identity.memory_config.get("learnings")
            and budget_chars > 0
        ):
            relevant = await learning_store.find_relevant(
                user_text,
                agent_id=agent_id,
                org_id=org_id,
            )
            budget_chars = _apply_learnings(
                relevant,
                kind="matched",
                use_rca_prefix=False,
                budget_chars=budget_chars,
                system_parts=system_parts,
                kept_ids=kept_ids,
            )

        budget_chars = await _apply_memory(
            context_assembly_policy,
            project_id=project_id,
            run_id=run_id,
            agent_id=agent_id,
            session_id=session_id,
            query=user_text,
            budget_chars=budget_chars,
            system_parts=system_parts,
        )

        result_messages = _assemble_messages(
            messages, system_parts, enable_cache_breakpoints=enable_cache_breakpoints
        )
        return result_messages, kept_ids


async def _apply_memory(
    policy: ContextAssemblyPolicy | None,
    *,
    project_id: str,
    run_id: str,
    agent_id: str,
    session_id: str,
    query: str,
    budget_chars: int,
    system_parts: list[str],
) -> int:
    """Append the assembled memory block and return the remaining budget.

    The content is sanitized for the same reason learnings are, and the reason
    is not weaker here: episodic memories are model-authored, they persist, and
    they are re-injected into the *system* prompt on later turns. A memory
    carrying `</maistro:corrections>` would close a block it does not own and
    promote everything after it to top-level instruction -- a stored prompt
    injection that survives the session that planted it. The delimiter is the
    trust boundary, and every model-authored string crossing it is neutralized.

    The block is rendered whole or not at all: `assemble` has already spent its
    own budget on whole memories, so slicing the result here would reintroduce
    the fragment that packing exists to prevent.

    "No policy wired" and "no budget left" are answered here rather than at the
    call site so `build`, which is already at the complexity ceiling, gains a
    call and not a branch.
    """
    if policy is None or budget_chars <= 0:
        return budget_chars
    assembled = await policy.assemble(
        project_id=project_id,
        run_id=run_id,
        agent_id=agent_id,
        session_id=session_id,
        budget_tokens=budget_chars // _CHARS_PER_TOKEN,
        query=query,
    )
    if not assembled:
        return budget_chars
    block = f"<maistro:memory>\n{_neutralize_delimiters(assembled)}\n</maistro:memory>"
    if len(block) > budget_chars:
        logger.debug("Context budget: dropped the memory block (%d chars)", len(block))
        return budget_chars
    system_parts.append(block)
    return budget_chars - len(block)


def _apply_learnings(
    learnings: list[Any],
    *,
    kind: str,
    use_rca_prefix: bool,
    budget_chars: int,
    system_parts: list[str],
    kept_ids: list[int],
) -> int:
    """Render a learnings block, append it to ``system_parts``, record its kept
    ids, and return the remaining ``budget_chars``."""
    if not learnings:
        return budget_chars
    block, block_ids, added = _render_learnings_block(
        learnings,
        block_type=kind,
        budget_chars=budget_chars,
        use_rca_prefix=use_rca_prefix,
    )
    if block is not None:
        system_parts.append(block)
        budget_chars -= len(block)
        kept_ids.extend(block_ids)
    if added < len(learnings):
        logger.debug(
            "Context budget: dropped %d/%d %s learnings",
            len(learnings) - added,
            len(learnings),
            kind,
        )
    return budget_chars


def _assemble_messages(
    messages: list[dict[str, Any]],
    system_parts: list[str],
    *,
    enable_cache_breakpoints: bool,
) -> list[dict[str, Any]]:
    """Prepend the assembled system context to ``messages`` (merging into an
    existing system message if present) and optionally inject cache breakpoints."""
    assembled = "\n\n".join(system_parts)
    result_messages = list(messages)

    if assembled:
        if result_messages and result_messages[0].get("role") == "system":
            result_messages[0] = {
                "role": "system",
                "content": assembled + "\n\n" + result_messages[0]["content"],
            }
        else:
            result_messages.insert(0, {"role": "system", "content": assembled})

    if enable_cache_breakpoints:
        result_messages = inject_cache_breakpoints(result_messages)

    return result_messages


def inject_cache_breakpoints(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = list(messages)
    if not result or result[0].get("role") != "system":
        return result

    system_msg = dict(result[0])
    content = system_msg["content"]

    if isinstance(content, str):
        idx = content.find(_LEARNINGS_BOUNDARY)
        if idx > 0:
            stable = content[:idx].rstrip()
            dynamic = content[idx:]
            blocks: list[dict[str, Any]] = [
                {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": dynamic},
            ]
        else:
            blocks = [
                {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}},
            ]
        system_msg["content"] = blocks
    elif isinstance(content, list):
        blocks = []
        for i, block in enumerate(content):
            new_block = dict(block)
            if i == 0 and "cache_control" not in new_block:
                new_block["cache_control"] = {"type": "ephemeral"}
            blocks.append(new_block)
        system_msg["content"] = blocks

    result[0] = system_msg
    return result
