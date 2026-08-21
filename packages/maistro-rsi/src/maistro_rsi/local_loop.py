"""Safe, capped, *local* recursive-self-improvement loop.

The full `RsiCycle` (`maistro_rsi.runner`) runs inside a Docker micro-VM, drives
an external coding agent (Codex CLI), scores candidates against SWE-Bench-class
benchmarks, and can open PRs. That is the eventual shape. This module is the
first, deliberately small increment underneath it:

  - **Native provider.** The patch is produced by the *native* builders agent
    loop (`maistro_bootstrap.builders` — the same engine behind `maistro
    builders`), wrapped as an `ApplyPatchFn`. No external Codex dependency.
  - **Safe + local.** Everything happens in throwaway git worktrees under a
    work root. The user's real checkout and its branches are never touched, and
    nothing is pushed or PR'd. The only "commit" is to an internal
    ``rsi-baseline`` branch inside a *clone*.
  - **Tests gate every promotion.** A cycle's candidate is promoted to the new
    baseline only if it (a) actually changed something and (b) the repo's own
    test command passes. This is the recursive ratchet — each accepted cycle
    becomes the base the next cycle builds on.
  - **Fixed cap.** The loop runs at most ``max_cycles`` cycles, so a first run
    is observable and can't run away. (Quota-headroom pacing via
    `maistro_rsi.quota_burn` is the next increment, not this one.)

It composes with the rest of the package: `LocalSandbox` satisfies the same
`MicroVmSandbox` protocol the micro-VM backend does, and the apply-patch
callable satisfies the same `ApplyPatchFn` the full runner consumes — so the
native provider built here drops straight into `RsiCycle` later.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from maistro_evolve.improvement import BudgetTier, ImprovementKind
from maistro_rsi.competitors import Competitor
from maistro_rsi.merge import greedy_merge
from maistro_rsi.protocols import ApplyPatchFn, MicroVmSandbox

logger = structlog.get_logger()


def _prompt_cache_enabled() -> bool:
    """Opt-in Anthropic prompt caching for the builders LLM calls, off by default.

    Enable with ``MAISTRO_BUILDERS_PROMPT_CACHE=1`` (also on/true/yes). Gated
    because it (a) only helps Anthropic-family models and (b) trades cache warmth
    against the per-cycle model diversity the tournament relies on — see the
    no-cache-for-diversity note in PR #239. A no-op for non-Anthropic models even
    when on (ResponsesAPICallable gates on the model name).
    """
    return os.environ.get("MAISTRO_BUILDERS_PROMPT_CACHE", "").strip().lower() in (
        "1",
        "on",
        "true",
        "yes",
    )


_DEFAULT_OBJECTIVE = (
    "Make exactly one small, safe, self-contained improvement to this codebase, "
    "in priority order: fix a real bug (test-first: add the failing test, then the "
    "fix), add a focused unit test for currently-untested behavior, strengthen a "
    "weak test assertion — and only if the code is already well-tested, improve a "
    "type hint or docstring. Read files before you edit them, keep the diff "
    "minimal, and do not break existing behavior. "
    "Use only the read_file, write_file and search tools — do NOT run git, "
    "commit, or shell commands: the harness stages, commits, and runs the tests "
    "for you after you finish. If you cannot find a safe improvement, make no "
    "changes and stop."
)


def _targeted_objective(path: str) -> str:
    """Build a per-cycle objective that names one explicit file to improve.

    Naming the file removes the discovery step that weak models fail at (they
    can't reliably search for a target), so each cycle is a concrete, bounded
    edit of a known file. Test-first by default: substantive verification work
    (a new test, a stronger assertion, a bug-fix) outranks docstring/type
    polish, which is a fallback only — mirroring the fitness signals
    (new_test/coverage-delta reward, doc-regression veto).
    """
    return (
        f"Improve the module `{path}`, in priority order: (1) add ONE focused unit test for "
        f"currently-untested behavior in it — create or extend its test file — and make sure it "
        f"passes; (2) fix a real bug if you find one, test-first (add the failing test, then the "
        f"fix); (3) strengthen a test assertion that checks too little. Only if the module is "
        f"already well-tested and correct, improve a type hint or docstring instead. First read "
        f"`{path}` with the read_file tool; use edit_file for targeted exact-string changes and "
        f"write_file only to create a new test file — do NOT rewrite existing files wholesale, "
        f"and do not reformat or touch lines unrelated to your change. Keep the diff minimal and "
        f"do not alter runtime behavior except to fix a bug. Edit only this module and its test "
        f"file. Do not run git or shell commands."
    )


# ---------------------------------------------------------------------------
# git plumbing (sync, shell=False — argv lists, no interpolation)
# ---------------------------------------------------------------------------


_GIT_CONFIG = (
    # core.longpaths lets git write objects when the worktree sits under a deep
    # path (a real hazard on Windows, where MAX_PATH is 260 and throwaway
    # worktrees nest under a work root). No-op elsewhere.
    "-c",
    "core.longpaths=true",
    # RSI commits are bot commits made in throwaway clones, which don't inherit
    # the source's (repo-local) identity and can't rely on a global one. Set the
    # identity per-invocation so commits never fail with "Author identity
    # unknown", independent of worktree/clone config inheritance.
    "-c",
    "user.email=rsi@maistro.local",
    "-c",
    "user.name=maistro-rsi",
    # These clones/worktrees hold agent-controlled content (patches applied by
    # the RSI loop). A malicious commit could ship a `.git/hooks/` script that
    # would otherwise execute on the host during any git operation here —
    # neutralize hooks unconditionally rather than trusting the content.
    "-c",
    "core.hooksPath=/dev/null",
)


def _git(
    cwd: Path, *args: str, check: bool = True, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *_GIT_CONFIG, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc


def _git_apply(cwd: Path, patch: str) -> bool:
    """Apply ``patch`` onto the worktree at ``cwd``; return whether it landed.

    A non-zero exit (a conflict with what's already applied) is the *signal*
    the greedy merge uses to drop a competing candidate — so this must not raise.
    """
    proc = subprocess.run(
        ["git", *_GIT_CONFIG, "apply", "--whitespace=nowarn", "-"],
        cwd=str(cwd),
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0


_TRANSIENT_ERROR_MARKERS = (
    "ratelimit",
    "rate limit",
    "429",
    "quota",
    "billing",
    "payment",
    "insufficient credit",
    "overloaded",
    "503",
    # An UNREACHABLE endpoint is capacity, not fitness — observed live when the
    # TabbyAPI process behind a local model died and the gateway surfaced
    # "InternalServerError: OpenAIException - Connection error."; the cycle
    # errored instead of benching the model, so never-idle never got to field
    # a healthy provider. Covers litellm's APIConnectionError spelling too.
    "connection error",
    "connectionerror",
    "connection refused",
    "502",
    "504",
)


# Cross-provider never-idle fallback pool (LocalRsiConfig.emergency_models default):
# spans cerebras / groq / openrouter-free / openrouter-paid so that when a run's
# roster provider is fully rate-limited, a DIFFERENT provider is still servable.
# Ordered most-capable-first; the loop picks the first non-benched one.
_DEFAULT_EMERGENCY_MODELS = (
    "or-qwen3-coder",
    "or-qwen36",
    "cerebras-glm-4.7",
    "groq-llama-4-scout-17b",
    "groq-llama-3.3-70b",
    "openrouter/openai/gpt-oss-120b:free",
)


def _entry_model(genome: Any) -> str:
    """The model of a genome's entry (fixer) node — the one that authors fixes."""
    nodes = genome.topology.nodes
    entry = next((n for n in nodes if n.id == genome.topology.entry_node), nodes[0])
    return str(entry.model)


def _is_transient_provider_error(text: str) -> bool:
    """Is this error a provider being temporarily unavailable (rate limit /
    quota / billing / overload) rather than evidence about the fix or genome?

    Transient errors bench the MODEL for a few cycles (it sits out) instead of
    scoring the genome or killing the run — capacity problems are not fitness.
    """
    lowered = text.lower()
    return any(marker in lowered for marker in _TRANSIENT_ERROR_MARKERS)


# Providers state their own wait inside 429 errors (formats catalogued in
# C:\maistro\MODEL-LIMITS.md): Groq puts "Please try again in 7.664s" in the
# body, Gemini a google.rpc.RetryInfo `"retryDelay": "58s"`, and several
# carriers a `retry-after: N` header that LiteLLM folds into the error text.
_RETRY_AFTER_PATTERNS = (
    re.compile(r'retrydelay"?\s*[:=]\s*"?(\d+(?:\.\d+)?)\s*s', re.IGNORECASE),
    re.compile(r"try again in\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE),
    re.compile(r"retry-after[\"':\s]+(\d+(?:\.\d+)?)", re.IGNORECASE),
)


def _parse_retry_after_seconds(text: str) -> float | None:
    """Extract the provider's own stated wait from an error, if it names one.

    The bench honors this over any fixed sit-out length — a 7s Groq RPM blip
    shouldn't cost minutes, and a 58s Gemini daily-quota wait shouldn't be
    retried in 10. Returns None when no wait is stated (fall back to cycles).
    """
    for pattern in _RETRY_AFTER_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _scouted_objective(path: str, instruction: str) -> str:
    """Wrap a scout's concrete instruction in the agent's tool-use guidance so
    every competitor implements the *same* identified improvement."""
    return (
        f"Improve the file `{path}`. A reviewer identified this specific improvement:\n"
        f"  {instruction}\n"
        f"Implement exactly that. First read `{path}` with the read_file tool, then make the "
        f"change with the edit_file tool (a targeted exact-string replacement) — do NOT rewrite "
        f"the whole file, do not reformat unrelated lines, and do not alter runtime behavior. "
        f"Use only read_file and edit_file — do not run git or shell commands."
    )


def _guess_test_path(target: str) -> str:
    """Best-effort test file for a source path: ``.../pkg/src/mod.py`` →
    ``.../pkg/tests/test_mod.py``. Used to show the scout the module's existing
    tests so it can reason about weak assertions / missing cases."""
    t = target.replace("\\", "/")
    stem = t.rsplit("/", 1)[-1]
    name = stem[:-3] if stem.endswith(".py") else stem
    if "/src/" in t:
        pkg_root = t.split("/src/", 1)[0]
        return f"{pkg_root}/tests/test_{name}.py"
    return f"tests/test_{name}.py"


def _fixer_objective(path: str, kind: ImprovementKind, instruction: str) -> str:
    """The tiered base-fixer scaffold: implement one scout item, with rules keyed
    to its kind. SPEC finishes contracted acceptance criteria (the biggest reward,
    claimed via @pytest.mark.ac); BACKLOG drafts a new spec contract instead of
    hacking a feature in raw; FEATURE (v2.0) work is ambitious and multi-file;
    everything else is a bounded, test-first, single-module change. This is the
    fixed task contract — the evolvable strategy layer is the genome's prompt."""
    if kind is ImprovementKind.SPEC:
        return (
            f"Implement this UNFULFILLED acceptance criterion (related module: `{path}`):\n"
            f"  {instruction}\n"
            "This finishes work the repo has already contracted in docs/specs/ — the highest-"
            "reward move available. Work test-first: write the test that PROVES the criterion, "
            'decorated with @pytest.mark.ac("SPEC-<id>/AC-<n>") using the exact ids from the '
            "instruction, confirm it fails, then implement until it passes with every existing "
            "test still green. Use read_file, edit_file and write_file across the files the "
            "criterion needs. Do not run git or shell commands."
        )
    if kind is ImprovementKind.BACKLOG:
        return (
            f"Draft a NEW spec contract for this capability idea (related module: `{path}`):\n"
            f"  {instruction}\n"
            "Create one markdown file under docs/specs/ following the existing SPEC-*.md "
            "convention: YAML frontmatter with a unique `id: SPEC-<date>-<short>` plus title/"
            "repo/kind/status/created, a short design section, and enumerated acceptance "
            "criteria as '- [ ] **AC-n**' checkboxes — each one concrete and testable. Do NOT "
            "implement the capability; the contract is the deliverable (implementation becomes "
            "future spec work). Read a neighboring docs/specs/SPEC-*.md first to match the "
            "format. Use read_file and write_file. Do not run git or shell commands."
        )
    if kind is ImprovementKind.FEATURE:
        return (
            f"Implement this enhancement to the `{path}` module:\n  {instruction}\n"
            "This is a substantial, ambitious change — design the improved capability or API and "
            "implement it across the files it needs. Prove it with NEW tests written first that "
            "specify the new behavior, and keep all existing tests green; preserve backward "
            "compatibility unless the enhancement explicitly supersedes it. Use read_file, "
            "edit_file and write_file across the files involved. Do not run git or shell commands."
        )
    return (
        f"Implement this specific improvement to `{path}`:\n  {instruction}\n"
        "Work test-first: add or extend the test for this module (create or extend its test file) "
        "so it fails against the current code, then change the code until it passes. Keep the diff "
        "minimal and focused on this one item — do not reformat or touch unrelated lines, and all "
        "existing tests must stay green. Edit only this module and its test file, using read_file, "
        "edit_file and write_file. Do not run git or shell commands."
    )


# ---------------------------------------------------------------------------
# LocalSandbox — a host-backed MicroVmSandbox
# ---------------------------------------------------------------------------


class LocalSandbox:
    """A `MicroVmSandbox` that runs directly on the host inside a worktree.

    No isolation beyond the working directory — this is the *safe local loop*
    backend, meant for running a self-improvement cycle against a throwaway
    clone of the repo, not for executing untrusted code. Snapshots are git
    commits so `restore` genuinely rewinds the tree (unlike the Docker backend,
    which can only record a label and rebuild from a ref).
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace)

    @property
    def workspace(self) -> Path:
        return self._workspace

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        def _run() -> tuple[int, str]:
            # shell=True: `command` is operator-supplied test/health config
            # (e.g. "pytest -q && ruff check"), not agent-controlled input.
            proc = subprocess.run(  # nosemgrep
                command,
                shell=True,  # nosemgrep
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

        return await asyncio.to_thread(_run)

    async def read_file(self, path: str) -> str:
        return await asyncio.to_thread((self._workspace / path).read_text, "utf-8")

    async def write_file(self, path: str, content: str) -> None:
        target = self._workspace / path

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        await asyncio.to_thread(_write)

    async def snapshot(self, label: str) -> str:
        del label  # bookkeeping only (microVM-backend parity); the id is the sha
        proc = await asyncio.to_thread(_git, self._workspace, "rev-parse", "HEAD")
        return proc.stdout.strip()

    async def restore(self, snapshot_id: str) -> None:
        await asyncio.to_thread(_git, self._workspace, "reset", "--hard", snapshot_id)

    async def destroy(self) -> None:
        # Worktrees are torn down by the loop that created them; nothing to do.
        return None

    async def __aenter__(self) -> LocalSandbox:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()


# ---------------------------------------------------------------------------
# Native builders provider — the ApplyPatchFn
# ---------------------------------------------------------------------------


# A resumed transcript must FIT back into the context window of whatever model
# resumes it — observed live: six resumed tool budgets accumulated a
# 45,439-token prompt against the local tier's 32,768 window and the gateway
# rejected the cycle (ContextWindowExceededError).
#
# Budgets are characters. RSI transcripts are almost entirely source code,
# diffs, and test output, which tokenize at ~2.5-3.5 chars/token (punctuation
# density, indentation runs, camelCase splits) — NOT prose's ~4. 60,000 chars
# is therefore ~20k tokens worst-case, leaving a 32k window room for the system
# prompt, tool schemas, and the response. Callers routing to a known
# larger-window model can raise `char_budget` per call; there is deliberately
# no model→window table here to silently rot.
_RESUME_CHAR_BUDGET = 60_000
_RESUME_ITEM_CAP = 16_000
# Distinct markers per direction. The input marker matters: appended to a
# truncated `tool_use` argument it is the model reading ITS OWN past write_file
# call — a marker that reads as truncated file content invites the model to
# re-issue the write with the marker inside, corrupting a real source file.
_ELIDED_OUTPUT = "\n[...tool output elided on resume...]"
_ELIDED_INPUT = (
    "\n[...tool arguments truncated in this resume record — historical entry, "
    "do not re-issue this call from what you see here...]"
)
# Backwards-compat alias (tests and older callers referenced the single marker).
_ELIDED = _ELIDED_OUTPUT


def _chars(messages: list[dict[str, Any]]) -> int:
    """Measured on the JSON wire form, not Python repr — repr quoting differs
    from JSON by a few percent, and this number is tuned against a hard
    ceiling."""
    try:
        return len(json.dumps(messages, default=str))
    except (TypeError, ValueError):
        return sum(len(str(m)) for m in messages)


def _shrink_block(block: Any, item_cap: int = _RESUME_ITEM_CAP) -> Any:
    """A copy of a content ``block`` with its oversized string payload(s) cut to
    their head — from EITHER direction a tool exchange carries bulk:

    - a ``tool_result``'s ``content`` — the SANDBOX's output (capped at 1MB by
      _OUTPUT_CAP);
    - a ``tool_use``'s ``input`` values — the LLM's OWN arguments (a
      write_file/edit_file call's ``content``/``old_string``/``new_string``),
      which routinely dwarf any sandbox output.
    """
    if not isinstance(block, dict):
        return block
    if isinstance(block.get("content"), str) and len(block["content"]) > item_cap:
        block = {**block, "content": block["content"][:item_cap] + _ELIDED_OUTPUT}
    if isinstance(block.get("input"), dict):
        shrunk = {
            k: (v[:item_cap] + _ELIDED_INPUT if isinstance(v, str) and len(v) > item_cap else v)
            for k, v in block["input"].items()
        }
        if shrunk != block["input"]:
            block = {**block, "input": shrunk}
    return block


def _shrink_stale_output(
    message: dict[str, Any], item_cap: int = _RESUME_ITEM_CAP
) -> dict[str, Any]:
    """A copy of ``message`` with oversized tool call inputs/outputs cut to their head."""
    content = message.get("content")
    if isinstance(content, str) and len(content) > item_cap:
        return {**message, "content": content[:item_cap] + _ELIDED_OUTPUT}
    if isinstance(content, list):
        blocks = [_shrink_block(block, item_cap) for block in content]
        if blocks != content:
            return {**message, "content": blocks}
    return message


def _split_units(
    transcript: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """(seed, units): seed is every leading message before the first assistant
    turn; each unit is one assistant turn plus the messages answering its tool
    calls.

    Structure-derived, not index arithmetic: the old ``del trimmed[2:4]``
    hard-coded a 2-message seed and strict pair parity, so a third seed message
    (e.g. recalled learnings from #257) would have been deleted while the
    comment said "never touching the seed", and any text-only assistant turn
    shifted parity and split a real pair — leaving an orphan tool_result most
    providers reject with a 400.
    """
    seed_end = 0
    while seed_end < len(transcript) and transcript[seed_end].get("role") != "assistant":
        seed_end += 1
    units: list[list[dict[str, Any]]] = []
    for message in transcript[seed_end:]:
        if message.get("role") == "assistant" or not units:
            units.append([message])
        else:
            units.append([*units.pop(), message])
    return list(transcript[:seed_end]), units


def _compact_unit(unit: list[dict[str, Any]], allowance: int) -> list[dict[str, Any]]:
    """Last resort: cut every string payload in ``unit`` so the whole unit fits
    ``allowance``. This is the aggregate cap the per-item cap cannot provide —
    three 15,999-char values in one block pass a 16,000 per-item cap while
    tripling the budget."""
    strings = 0
    for message in unit:
        content = message.get("content")
        if isinstance(content, str):
            strings += 1
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if isinstance(block.get("content"), str):
                        strings += 1
                    if isinstance(block.get("input"), dict):
                        strings += sum(1 for v in block["input"].values() if isinstance(v, str))
    per_value = max(200, allowance // max(1, strings))
    return [_shrink_stale_output(m, item_cap=per_value) for m in unit]


def _trim_for_resume(
    transcript: list[dict[str, Any]], char_budget: int = _RESUME_CHAR_BUDGET
) -> list[dict[str, Any]] | None:
    """Fit ``transcript`` under ``char_budget``, or return None if impossible.

    Levers are spent cheapest-first, re-measuring between steps, and the newest
    exchange — the one the model is about to answer — is touched only as a last
    resort:

    1. shrink STALE units' oversized payloads, oldest-first;
    2. drop stale units whole, oldest-first (never splitting a turn from its
       tool results, never touching the seed);
    3. shrink the newest unit's payloads;
    4. aggregate-compact the newest unit into whatever budget remains;
    5. still over — return None so the cycle ends BY DESIGN, the same contract
       _resume_transcript already has for its other unsafe case. The old code's
       ``len(trimmed) > 4`` loop exit returned an over-budget transcript with no
       log, and the next gateway call died with the exact
       ContextWindowExceededError this function exists to prevent.
    """
    if _chars(transcript) <= char_budget:
        return list(transcript)

    seed, units = _split_units(transcript)
    if not units:
        logger.warning(
            "rsi_resume_trim_impossible",
            reason="seed alone exceeds budget",
            seed_chars=_chars(seed),
            budget=char_budget,
        )
        return None

    def _fits() -> bool:
        return _chars(seed + [m for u in units for m in u]) <= char_budget

    # 1. stale payloads, oldest-first.
    for i in range(len(units) - 1):
        units[i] = [_shrink_stale_output(m) for m in units[i]]
        if _fits():
            break

    # 2. drop stale units, oldest-first.
    while not _fits() and len(units) > 1:
        del units[0]

    # 3-4. the newest unit, only once nothing stale remains.
    return _trim_newest_unit(seed, units, char_budget)


def _trim_newest_unit(
    seed: list[dict[str, Any]],
    units: list[list[dict[str, Any]]],
    char_budget: int,
) -> list[dict[str, Any]] | None:
    """Steps 3-5 of the trim: shrink, then aggregate-compact, the newest unit;
    None when even that cannot fit the budget."""

    def _flat() -> list[dict[str, Any]]:
        return seed + [m for u in units for m in u]

    if _chars(_flat()) > char_budget:
        units[-1] = [_shrink_stale_output(m) for m in units[-1]]
    if _chars(_flat()) > char_budget:
        allowance = char_budget - _chars(seed)
        if allowance > 0:
            units[-1] = _compact_unit(units[-1], allowance)
    if _chars(_flat()) > char_budget:
        logger.warning("rsi_resume_trim_over_budget", chars=_chars(_flat()), budget=char_budget)
        return None
    return _flat()


def _resume_transcript(
    result: dict[str, Any], char_budget: int = _RESUME_CHAR_BUDGET
) -> list[dict[str, Any]] | None:
    """The messages to continue from after `execute_turn`, or None when done.

    "max_turns" is TurnRunner's internal tool-budget stop, not the model
    finishing: the agent was cut off MID-WORK, with its whole tool transcript
    in ``result["messages"]``. Resuming from that transcript keeps the work's
    context (it ends with unanswered tool results, so the model just carries
    on). The one thing this must never do is echo the "(max turns reached)"
    sentinel back as assistant speech — a model shown that as its own words
    believes it announced running out of budget and quits (observed live: it
    hallucinated a "maximum number of turns (100)" and a "no git or shell
    commands" rule to justify stopping, and the cycle ended as "agent made no
    change"). Any other stop_reason means the agent chose to finish: None.
    """
    if result.get("stop_reason") != "max_turns":
        return None
    transcript = result.get("messages")
    if not isinstance(transcript, list) or not transcript:
        # A runner that doesn't hand back its transcript (injected fakes, older
        # TurnRunner) leaves nothing safe to resume from — end the cycle rather
        # than poison the context with the sentinel.
        return None
    return _trim_for_resume(list(transcript), char_budget=char_budget)


def make_builders_apply_patch(
    objective: str = _DEFAULT_OBJECTIVE,
    *,
    model: str | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    system_prompt: str | None = None,
    max_agent_turns: int = 6,
    isolation: str = "local",
    image: str = "maistro-builders:latest",
) -> ApplyPatchFn:
    """Build an `ApplyPatchFn` that drives the native builders agent loop.

    Returns an async callable ``apply(sandbox, workspace)`` that points the
    builders coding agent (the same `TurnRunner` engine behind `maistro
    builders`) at ``workspace`` and asks it to carry out ``objective``.
    ``max_agent_turns`` is the number of inner tool budgets a cycle may spend:
    each `execute_turn` runs up to `AgentLoopConfig.max_turns` tool calls, and
    when that budget runs out mid-work the next turn RESUMES from the full
    transcript (see `_resume_transcript`) instead of restarting cold.

    ``isolation`` selects the BuilderSandbox:
      - ``"local"``    — `LocalWorktreeSandbox`, edits run on the host (fast).
      - ``"container"``— `ContainerBuilderSandbox`, the agent's edits and commands
        run inside an ephemeral Docker container (ADR-093), then sync back to the
        worktree for the loop to commit. Requires ``image`` to be built.

    Model resolution is left to `ResponsesAPICallable` (``model=None`` →
    ``MAISTRO_BUILDERS_MODEL``/``DEFAULT_MODEL`` from the loaded ``.env``).
    """

    async def _run_turns(session: object, cycle_model: str | None = None) -> None:
        from maistro_bootstrap.builders.agent_loop import AgentLoopConfig, TurnRunner
        from maistro_bootstrap.builders.responses_callable import ResponsesAPICallable

        # Factory `model` is an explicit operator choice and wins; otherwise the
        # per-cycle model (the quota-burn scheduler's pick, threaded through
        # ApplyPatchFn's third argument) applies.
        effective_model = model or cycle_model
        config = AgentLoopConfig(model=effective_model) if effective_model else AgentLoopConfig()
        runner = TurnRunner(session=session, config=config)  # type: ignore[arg-type]
        # 300s timeout: the code group load-balances across reasoning deployments
        # (gpt-oss-120b on Cerebras at 5 RPM) whose queueing + long generations
        # overran the default 120s in a live run (httpx.ReadTimeout).
        runner.set_llm(
            ResponsesAPICallable(
                model=effective_model,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=300.0,
                prompt_cache=_prompt_cache_enabled(),
            )
        )

        # The genome's evolvable strategy prompt (when supplied) becomes the system
        # message; otherwise the builders default. The task (objective) is the user
        # message either way, so mutation tunes *approach*, not the task contract.
        messages: list[dict[str, object]] = [
            {"role": "system", "content": system_prompt or config.system_prompt},
            {"role": "user", "content": objective},
        ]
        for turn in range(max_agent_turns):
            result = await runner.execute_turn(messages=messages)
            await logger.ainfo(
                "rsi_local_agent_turn",
                turn=turn + 1,
                stop_reason=result.get("stop_reason"),
                content_preview=str(result.get("content", ""))[:160],
            )
            # execute_turn resolves its own internal tool loop (it never
            # returns "tool_use"); the only continue case is an exhausted
            # inner tool budget, resumed with the full transcript so the agent
            # keeps its context — never the "(max turns reached)" sentinel.
            resumed = _resume_transcript(result)
            if resumed is None:
                break
            messages = resumed

    async def apply(
        sandbox: MicroVmSandbox, workspace: str, cycle_model: str | None = None
    ) -> None:
        # Imported lazily so the package stays importable without the builders
        # extras installed (mirrors _builders_tui.py's own lazy import).
        from maistro_bootstrap.builders.session import BuilderSession

        work_path = Path(workspace)
        if isolation == "container":
            from maistro_bootstrap.builders.container_sandbox import ContainerBuilderSandbox

            with ContainerBuilderSandbox(work_path, image=image) as csbx:
                await _run_turns(BuilderSession(sandbox=csbx), cycle_model)
                # Agent ran isolated in the container; bring its edits back to the
                # host worktree so the loop can stage/commit/test them.
                csbx.sync_to_host()
        else:
            from maistro_bootstrap.builders.sandbox import LocalWorktreeSandbox

            await _run_turns(BuilderSession(sandbox=LocalWorktreeSandbox(work_path)), cycle_model)

    return apply


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


@dataclass
class LocalRsiConfig:
    """Inputs for one capped local self-improvement run."""

    repo_path: str
    test_command: str
    work_root: str
    max_cycles: int = 3
    objective: str = _DEFAULT_OBJECTIVE
    # Explicit files to improve, one per cycle (rotated). When set, each cycle
    # gets a targeted objective naming its file instead of the generic
    # `objective` — capable models edit a named file reliably, where weak ones
    # fail to discover a target by searching.
    targets: list[str] = field(default_factory=list)
    model: str | None = None
    agent_turns_per_cycle: int = 6
    # Larger turn budget for a FEATURE (v2.0) slot — ambitious, multi-file work
    # (ImprovementKind.FEATURE unlocks it; bounded kinds use agent_turns_per_cycle).
    feature_agent_turns: int = 15
    # "local" (host worktree) or "container" (ADR-093 Docker isolation).
    isolation: str = "local"
    sandbox_image: str = "maistro-builders:latest"
    baseline_branch: str = "rsi-baseline"
    test_timeout: int = 900
    # When True, promotion is decided by the full multi-signal Scorecard
    # (gates + weighted scores) instead of the bare test_command, and each
    # decision is logged via scorecard.explain(). Requires the quality tools
    # (ruff/mypy/bandit/coverage/…) to be importable in the run environment.
    use_fitness: bool = False
    coverage_source: str = "."
    # pytest args for the coverage run (e.g. a scoped test path). Empty means a
    # bare `pytest` — which, in a monorepo with many testpaths, runs the whole
    # suite every cycle; scope it to keep a fitness run tractable.
    coverage_pytest_args: str = ""
    # Tournament (ADR-070126-6386 / SPEC-070126-9d37). Each cycle runs every
    # competitor (a fixer config = evolve NodeGenome projection) on the same
    # target, scores them, and combines the results: same-region → highest
    # composite wins; disjoint regions → both kept. Empty ⇒ a single attempt
    # with `model` (the classic one-shot cycle).
    competitors: list[Competitor] = field(default_factory=list)
    # When set, one model reads the file and names the shared improvement all
    # competitors implement (a fairer head-to-head than each inventing its own).
    scout: bool = False
    scout_model: str | None = None
    # Ordered fallback catalog the scout tries in turn (skipping any that are
    # currently benched) instead of depending on one static model — a single
    # chronically-benched scout model was observed to silently zero the scout
    # for the rest of a run (scout_shortlist swallows the error and returns
    # []). Empty means "use genome_models" (already the full run roster in
    # live-evolution mode), falling back to [model] if that's empty too — see
    # _scout_fallback_catalog(). The actual try-in-order and skill-ranking
    # happens at runtime (scout_fallback.py); this is just the candidate pool.
    scout_fallback_models: list[str] = field(default_factory=list)
    # Stage 4 (ADR-070126-6386): when set, after the run each promotion is
    # exported here as a git-am-able patch plus a manifest.json, for the harvester
    # to open PRs grouped by file. This is the durable output of an isolated run.
    export_patches: str | None = None
    # Unified live evolution (ADR-070126-6386 v2, "the run IS the gym"): when a
    # PopulationStore path is given, the genome population IS the tournament
    # roster — each cycle's REAL composites fold back into the genomes (EMA),
    # same-objective variants fight Elo battles, then cull/breed/hyper-mutation
    # run between cycles and the children join the next cycle's roster, verified
    # by actual work. No separate training evaluations exist; fixes are kept
    # (promoted/exported) exactly as in a plain run. The population persists, so
    # every run continues the lineage.
    genome_db: str | None = None
    # Models to seed the genome population across in live mode (one seed genome
    # per model, so evolution learns per-model differences from cycle one).
    # Empty ⇒ fall back to [model]. Top-up seeding only — an existing lineage in
    # genome_db is continued, never buried.
    genome_models: list[str] = field(default_factory=list)
    # Operator goal threaded into the hyper-mutator's meta-prompt in live mode.
    evolve_goal: str = ""
    # Roster cap per cycle in live mode (genomes beyond this wait their turn;
    # unscored children get priority so verification never starves).
    roster_size: int = 4
    # NEVER-IDLE fallback: when EVERY genome's model is benched (whole roster
    # rate-limited/quota-drained), spawn a fresh genome onto the first SERVABLE
    # model from this cross-provider pool so the cycle still does real work
    # instead of no-opping. Empty ⇒ `_DEFAULT_EMERGENCY_MODELS`. A different
    # provider here (cerebras/groq vs openrouter) is what rescues a run whose
    # roster provider is fully rate-limited.
    emergency_models: list[str] = field(default_factory=list)
    # NEVER-IDLE FLOOR: a model served from local hardware (e.g. TabbyAPI/ExLlamaV3
    # on this box's GPU), consulted only when the ENTIRE cross-provider emergency
    # pool is benched too. Local hardware has no RPM/RPD/credit to exhaust, so it
    # is the one tier that cannot rate-limit — it keeps cadence, lineage and RLPHD
    # state alive through a quota outage that would otherwise stall the run for
    # hours. Deliberately NOT a member of `emergency_models`: that pool ranks by
    # reliability (defaulting to 1.0 for an unseen model) and a local model never
    # benches, so inside the pool it would out-rank real cloud models and quietly
    # become PRIMARY — the opposite of a last resort. Cloud-first has to hold by
    # construction, not by reliability arithmetic. Empty ⇒ no local tier.
    local_fallback_model: str = ""
    # Model bench: a competitor whose model hits a TRANSIENT provider error
    # (429/rate-limit/quota/billing) sits out instead of dying — no eval burned,
    # no stub folded into its genome, seat freed for others. The sit-out length
    # honors the provider's own stated retry-after when the error names one;
    # otherwise it defaults to this many cycles' worth of estimated wall-clock,
    # doubling on each consecutive bench of the same model (a chronically
    # exhausted daily quota backs off instead of burning a probe every cycle).
    bench_cycles: int = 3
    # Second-opinion LLM regression check (ADR-070126-6386 v3): a narrow judge
    # pass over every candidate that already cleared the deterministic gates,
    # aimed at semantic regressions no existing test covers (a data-shape
    # conversion silently narrowed, an untested branch riding on an unrelated
    # test's credit). Default on; set False to skip the extra LLM call.
    regression_judge: bool = True
    # Checkpoint-time RLPHD promotion review (SPEC-248 / promotion_review.py):
    # a low-confidence promotion (predicted human-approval p below its
    # adaptive theta) gets reverted so nothing keeps building on top of it,
    # patch saved for later human approve/deny. Default on; set False to
    # disable (e.g. a test exercising unrelated checkpoint mechanics that
    # never anticipated a revert).
    promotion_review: bool = True
    # Checkpointing for long runs. Every ``report_every`` cycles (0 = only at the
    # end), write a progress report (markdown + JSON) into ``report_dir`` and
    # refresh a rolling, harvestable patch export of everything promoted so far.
    # The baseline keeps ratcheting forward across the whole run — a checkpoint is
    # an observation point, not a reset — so each report covers cumulative
    # progress and the export always holds the complete promotion set to date
    # (recoverable if a long run is interrupted). Point ``report_dir`` at a path
    # OUTSIDE the edited workspace (e.g. a host-mounted dir) to get reports out of
    # an isolated run without exposing them to the agent.
    report_every: int = 0
    report_dir: str | None = None


@dataclass
class _VariantResult:
    """One competitor's attempt: its worktree/branch, whether it passed the
    gates, and its composite — the raw material the cycle ranks and merges."""

    branch: str
    cycle_dir: Path
    label: str = ""
    changed: bool = False
    accepted: bool = False
    composite: float = 0.0
    tests_passed: bool = False
    files_touched: int = 0
    changed_files: list[str] = field(default_factory=list)
    note: str = ""
    # True when the attempt raised (bad apply, git failure, fitness crash) — kept
    # distinct from a genuine no-op so the cycle summary never reports a crashed
    # variant as "agent made no change".
    errored: bool = False
    # Which shortlist slot this variant attempted (same slot ⇒ same objective ⇒
    # a fair Elo battle in live-evolution mode), which model ran it, and — when
    # the competitor was projected from a genome — which genome authored it.
    slot: int = 0
    model: str = ""
    genome_id: str | None = None
    # The ImprovementKind of the slot's scout item — reports and evolution can
    # see WHICH rung of the maturity ladder the work was on.
    kind: ImprovementKind = ImprovementKind.DOC
    # The second-opinion LLM regression judge's raw score (None if the judge
    # never ran) — survives past its pass/fail gate for the checkpoint-time
    # RLPHD reviewer to use as prediction evidence.
    regression_judge_score: float | None = None
    # Compact acceptance evidence (per-gate pass/fail, composite, mutation score)
    # lifted from the Scorecard, so a promotion can be annotated onto its commit
    # as a git-notes trace record (trace_notes.py) without re-deriving from logs.
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class CycleOutcome:
    index: int
    changed: bool
    tests_passed: bool
    promoted: bool
    files_touched: int = 0
    target: str = ""
    note: str = ""
    composite: float = 0.0
    # The promoted merge commit's sha, its (representative, top-scored) kind,
    # and the regression judge's raw score — the evidence a checkpoint-time
    # RLPHD reviewer needs, without re-deriving it from logs.
    sha: str = ""
    kind: ImprovementKind = ImprovementKind.DOC
    regression_judge_score: float | None = None


@dataclass
class LocalRsiResult:
    cycles: list[CycleOutcome] = field(default_factory=list)
    baseline_dir: str = ""

    @property
    def promotions(self) -> int:
        return sum(1 for c in self.cycles if c.promoted)

    def summary(self) -> str:
        lines = [f"RSI local loop: {self.promotions}/{len(self.cycles)} cycles promoted"]
        for c in self.cycles:
            mark = (
                "[promoted]" if c.promoted else ("[no change]" if not c.changed else "[rejected]")
            )
            detail = f"tests={'pass' if c.tests_passed else 'fail'} files={c.files_touched}"
            tgt = f" {c.target}" if c.target else ""
            note = f" - {c.note}" if c.note else ""
            lines.append(f"  cycle {c.index}:{tgt} {mark}  ({detail}){note}")
        lines.append(f"  baseline: {self.baseline_dir} (branch {self.promotions} promotions deep)")
        return "\n".join(lines)


def build_checkpoint_report(
    cycles: list[CycleOutcome],
    *,
    total_planned: int,
    baseline_dir: str,
    window: int,
    label: str = "",
    population_summary: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Render a progress report over ``cycles`` run so far — cumulative totals
    plus a detail of the most recent ``window`` cycles. Pure: derived entirely
    from the outcome list (and, in live mode, the population snapshot), so
    it's testable without git or an agent.

    ``population_summary`` (see ``LocalRsiLoop._population_summary``) is only
    present in unified live-evolution mode; when given, an "## Evolution"
    section reports WORK (promotions, above) alongside LEARNING (population
    size/generations, the fittest genomes, per-model reliability, who's
    currently benched, and the newest written lineage memory).

    Returns ``(markdown, machine_json)``. ``label`` distinguishes an interim
    checkpoint ("cycle 5") from the "final" report in headings.
    """
    done = len(cycles)
    promoted = [c for c in cycles if c.promoted]
    per_file = Counter(c.target for c in promoted if c.target)
    # Every promoted cycle counts — 0.0 is a valid promoted composite (a
    # non-fitness run defaults to 0.0, and an accepted scorecard can compose to
    # 0.0), so filtering truthy values would overstate the average.
    composites = [c.composite for c in promoted]
    avg_composite = round(sum(composites) / len(composites), 3) if composites else 0.0
    recent = cycles[-window:] if window > 0 else cycles
    heading = label or (f"cycle {done}" if done else "start")

    data: dict[str, Any] = {
        "checkpoint": heading,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cycles_run": done,
        "cycles_planned": total_planned,
        "promotions": len(promoted),
        "promotion_rate": round(len(promoted) / done, 3) if done else 0.0,
        "avg_composite": avg_composite,
        "files_improved": dict(per_file),
        "baseline_dir": baseline_dir,
        "recent": [
            {
                "index": c.index,
                "target": c.target,
                "promoted": c.promoted,
                "changed": c.changed,
                "tests_passed": c.tests_passed,
                "files_touched": c.files_touched,
                "composite": c.composite,
                "note": c.note,
            }
            for c in recent
        ],
    }

    lines = [
        f"# RSI checkpoint — {heading} / {total_planned} planned",
        "",
        f"_generated {data['generated_at']}_",
        "",
        "## Cumulative",
        f"- Cycles run: **{done} / {total_planned}**",
        f"- Promotions: **{len(promoted)}** ({data['promotion_rate']:.0%} of cycles run)",
        f"- Distinct files improved: **{len(per_file)}**",
        f"- Avg composite (promoted): **{avg_composite}**",
        f"- Baseline: `{baseline_dir}` — {len(promoted)} promotions deep",
    ]
    if per_file:
        lines += ["", "## Per-file promotions"]
        lines += [f"- `{f}`: {n}" for f, n in per_file.most_common()]
    lines += ["", f"## Recent window (last {len(recent)} cycle(s))"]
    for c in recent:
        mark = "promoted" if c.promoted else ("no change" if not c.changed else "rejected")
        detail = f"composite={c.composite}" if c.promoted else c.note or ""
        tgt = f" {c.target}" if c.target else ""
        lines.append(f"- cycle {c.index}:{tgt} — **{mark}** {detail}".rstrip())
    if population_summary is not None:
        data["evolution"] = population_summary
        lines += _evolution_report_lines(population_summary)
    return "\n".join(lines) + "\n", data


def _evolution_report_lines(summary: dict[str, Any]) -> list[str]:
    """Render ``LocalRsiLoop._population_summary`` as the "## Evolution"
    section: WORK is promotions (above); this is LEARNING — is the population
    actually evolving, not just producing accepted patches."""
    lines = ["", "## Evolution"]
    gens = summary.get("generations") or {}
    pop_line = f"- Population: **{summary.get('population_size', 0)}** genome(s)"
    if gens:
        histogram = ", ".join(f"gen {g}: {n}" for g, n in gens.items())
        pop_line += f" across **{len(gens)}** generation(s): {histogram}"
    lines.append(pop_line)
    top = summary.get("top_genomes") or []
    if top:
        lines += ["", "### Fittest genomes"]
        for g in top:
            lines.append(
                f"- `{g.get('name')}` (gen {g.get('generation')}, {g.get('model')}) — "
                f"fitness={g.get('fitness')} code_rsi={g.get('code_rsi')} "
                f"tdd_rigor={g.get('tdd_rigor')} test_style={g.get('test_style')}"
            )
    reliability = summary.get("reliability") or {}
    if reliability:
        lines += ["", "### Model reliability"]
        lines += [f"- `{m}`: {round(v, 3)}" for m, v in sorted(reliability.items())]
    benched = summary.get("benched_models") or []
    if benched:
        lines += ["", f"### Currently benched: {', '.join(f'`{m}`' for m in benched)}"]
    memory = summary.get("memory") or {}
    if memory:
        lines += ["", "### Newest lineage memory (fittest genome)"]
        lines += [f"- **{k}**: {v}" for k, v in memory.items()]
    return lines


class LocalRsiLoop:
    """Run up to ``max_cycles`` self-improvement cycles against a throwaway clone.

    Each cycle branches a fresh worktree off the current baseline, lets the
    native builders agent patch it, runs the test command, and fast-forwards the
    baseline only if the change is real *and* green. Winners ratchet forward;
    losers are discarded. Nothing leaves the work root.
    """

    def __init__(self, config: LocalRsiConfig, apply_patch: ApplyPatchFn | None = None) -> None:
        self._config = config
        self._injected_apply = apply_patch
        self._baseline = Path(config.work_root) / "baseline"
        self._baseline_cov: float | None = None  # cached; invalidated on promote
        self._start_ref: str | None = None  # baseline sha before any promotion
        # Checkpoint-time RLPHD review (promotion_review.py) scans only commits
        # since the LAST review pass — set to _start_ref once the baseline is
        # ready, advanced after each _review_promotions() call.
        self._last_reviewed_ref: str | None = None
        # Commits on baseline_branch that are real (a resume commit, a revert)
        # but aren't in result.cycles as a promotion — _check_persistence_integrity
        # must add these back in, or every resume/revert reads as a false
        # "history diverged from the promotion count" alarm. export_promotions
        # also excludes these shas: a reverted promotion and its own revert
        # commit both represent "nothing net happened," not exportable work.
        self._non_promotion_commits = 0
        self._excluded_from_export: set[str] = set()
        # Scout model fallback (scout_fallback.py): loaded lazily on first use
        # (needs report_dir, which _setup_baseline doesn't touch) so it survives
        # restarts the same way population.db/rlphd_state.json do; None until
        # then. _last_scout_model records which model actually served THIS
        # cycle, so a promotion can credit it.
        self._scout_fallback: Any = None
        self._last_scout_model: str | None = None
        # Unified live evolution (genome_db set): the population that IS the
        # roster, an in-run Elo ladder, and the label→genome mapping for folding
        # real composites back into the genomes that authored them.
        self._population: Any = None
        self._elo: Any = None
        self._label_to_genome: dict[str, str] = {}
        # Model bench: model -> wall-clock deadline (time.monotonic()) until
        # which it sits out. Deadlines come from the provider's own retry-after
        # when the error states one; otherwise from bench_cycles worth of
        # estimated cycle time, doubling per consecutive bench (see
        # _bench_model). _bench_counts tracks the consecutive-bench streak,
        # reset by any successful scoring of the model.
        self._bench: dict[str, float] = {}
        self._bench_counts: dict[str, int] = {}
        self._benched_this_cycle: set[str] = set()  # models benched during current cycle
        # Per-file uncovered lines from the baseline coverage run — the scout
        # targets real gaps, and an empty list is the earned-ambition trigger.
        self._baseline_missing: dict[str, list[int]] = {}
        # Contracted-but-unproven spec ACs (spec_tracker.spec_gaps), cached per
        # baseline state — refreshed when a promotion may have claimed some.
        self._spec_gaps: dict[str, list[str]] | None = None
        # Per-model reliability (run-local EMA, starts 1.0): transient provider
        # failures decay it, successes recover it. Multiplied into genome fitness
        # so a genome married to a flaky provider scores lower than the SAME slot
        # settings on a dependable model — evolution then re-tries winning
        # strategies on other carriers. Deliberately not persisted: provider
        # health is temporal; yesterday's outage shouldn't punish forever.
        self._reliability: dict[str, float] = {}
        if config.genome_db:
            from maistro_evolve.tournament import EloTournament
            from maistro_rsi.evolve_bridge import open_population, seed_population

            self._population = open_population(config.genome_db)
            # Top-up seeding: an existing lineage is continued, never buried.
            # Seed across every roster model so evolution learns per-model
            # differences from cycle one (genome_models beats a single model).
            seed_models = config.genome_models or ([config.model] if config.model else None)
            seed_population(
                self._population,
                max(config.roster_size, len(config.genome_models)),
                models=seed_models,
            )
            self._elo = EloTournament()

    def _baseline_coverage(self) -> float | None:
        if not self._config.use_fitness:
            return None
        if self._baseline_cov is None:
            from maistro_evolve.coverage_gate import measure_coverage_detailed

            # One instrumented run yields both the total (the gate) and each
            # file's missing lines (the scout's real targets) — no extra cost.
            self._baseline_cov, self._baseline_missing = measure_coverage_detailed(
                self._baseline,
                source=self._config.coverage_source,
                pytest_args=self._config.coverage_pytest_args,
            )
        return self._baseline_cov

    def _uncovered_for(self, target: str) -> list[int]:
        """The baseline's uncovered line numbers for ``target`` (empty = fully
        covered — the earned-ambition trigger, or coverage unavailable)."""
        self._baseline_coverage()  # ensure the cache is populated
        return self._baseline_missing.get(target.replace("\\", "/"), [])

    def _spec_gaps_text(self) -> str:
        """Contracted-but-unproven ACs, rendered for the scout prompt (cached)."""
        if self._spec_gaps is None:
            from maistro_rsi.spec_tracker import spec_gaps

            try:
                self._spec_gaps = spec_gaps(self._baseline)
            except Exception:  # sensing must never stall a cycle
                self._spec_gaps = {}
        from maistro_rsi.spec_tracker import format_gaps

        return format_gaps(self._spec_gaps)

    def _target_for_cycle(self, index: int) -> str:
        if self._config.targets:
            return self._config.targets[(index - 1) % len(self._config.targets)]
        return ""

    def _objective_for_cycle(self, index: int) -> str:
        target = self._target_for_cycle(index)
        return _targeted_objective(target) if target else self._config.objective

    def _scout_fallback_path(self) -> Path | None:
        if not self._config.report_dir:
            return None
        return Path(self._config.report_dir) / "scout_fallback.json"

    def _scout_fallback_catalog(self) -> list[str]:
        """The candidate pool the scout tries in turn. Explicit
        ``scout_fallback_models`` wins; otherwise ``genome_models`` (already
        the full live-evolution roster); otherwise the single ``model``."""
        if self._config.scout_fallback_models:
            return list(self._config.scout_fallback_models)
        if self._config.genome_models:
            return list(self._config.genome_models)
        return [self._config.model] if self._config.model else []

    def _ensure_scout_fallback_loaded(self) -> None:
        if self._scout_fallback is None:
            from maistro_rsi.scout_fallback import ScoutFallbackState, load_state

            path = self._scout_fallback_path()
            self._scout_fallback = load_state(path) if path is not None else ScoutFallbackState()

    def _save_scout_fallback(self) -> None:
        path = self._scout_fallback_path()
        if path is not None and self._scout_fallback is not None:
            from maistro_rsi.scout_fallback import save_state

            save_state(path, self._scout_fallback)

    def _next_scout_order(self) -> list[str]:
        """This cycle's ordered candidates, advancing (and persisting) the
        round-robin rotation for next time — see scout_fallback.next_order."""
        from maistro_rsi.scout_fallback import next_order

        self._ensure_scout_fallback_loaded()
        order, self._scout_fallback = next_order(
            self._scout_fallback, self._scout_fallback_catalog()
        )
        self._save_scout_fallback()
        return order

    def _record_scout_success(self, model: str | None) -> None:
        """Credit the model that served as scout in a cycle that got promoted
        — the only signal that decides the fallback order over time."""
        if not model:
            return
        from maistro_rsi.scout_fallback import record_success

        self._ensure_scout_fallback_loaded()
        self._scout_fallback = record_success(self._scout_fallback, model)
        self._save_scout_fallback()

    def _cycle_slots(self, index: int) -> list[tuple[str, BudgetTier, ImprovementKind]]:
        """The (objective, budget, kind) slots competitors fill this cycle.

        With ``scout`` on, the scout reads the target's source, existing tests,
        its real uncovered lines, and the repo's unimplemented spec ACs, and
        returns a ranked shortlist of typed improvements; each becomes a slot
        whose objective is the tiered fixer scaffold and whose budget/kind route
        everything downstream (SPEC/BACKLOG/FEATURE unlock the big budget).
        Competitors spread across the slots (complementary) and, over runs,
        collide on hot ones (competitive). Without scout — or on a
        silent/garbled scout — a single bounded slot carries the classic
        targeted/generic objective so a cycle never stalls.

        The scout model is NOT static: a chronically-benched single model
        used to silently zero the scout for every remaining cycle
        (scout_shortlist swallows LLM errors and returns ``[]``). Instead we
        try every model in the skill-ranked fallback order (scout_fallback.py),
        skipping any currently benched, until one produces a real shortlist.
        """
        self._last_scout_model = None
        target = self._target_for_cycle(index)
        fallback = [(self._objective_for_cycle(index), BudgetTier.BOUNDED, ImprovementKind.DOC)]
        if not (self._config.scout and target):
            return fallback
        try:
            source = (self._baseline / target).read_text(encoding="utf-8")
        except OSError:
            return fallback
        try:
            tests = (self._baseline / _guess_test_path(target)).read_text(encoding="utf-8")
        except OSError:
            tests = ""
        from maistro_bootstrap.builders.responses_callable import ResponsesAPICallable
        from maistro_rsi.scout import scout_shortlist

        fallback_order = self._next_scout_order()
        # An explicit scout_model is a preference, not an exclusive pin — it's
        # tried first, but a chronically-benched model still fails over into
        # the skill-ranked list rather than zeroing the scout for the rest of
        # the run (the exact failure this fallback exists to prevent).
        candidates = ([self._config.scout_model] if self._config.scout_model else []) + [
            m for m in fallback_order if m != self._config.scout_model
        ]
        items: list[Any] = []
        scout_used: str | None = None
        for model in candidates:
            if self._benched(model):
                continue
            llm = ResponsesAPICallable(model=model)
            items = scout_shortlist(
                source,
                tests,
                self._uncovered_for(target),
                llm,
                spec_gaps=self._spec_gaps_text(),
                max_items=3,
            )
            if items:
                scout_used = model
                break
        if not items:
            return fallback
        self._last_scout_model = scout_used
        logger.info(
            "rsi_local_scout",
            index=index,
            target=target,
            scout_model=scout_used,
            items=[{"kind": it.kind.value, "instruction": it.instruction[:120]} for it in items],
        )
        return [
            (_fixer_objective(target, it.kind, it.instruction), it.kind.budget, it.kind)
            for it in items
        ]

    # Rough wall-clock cost of one cycle (agent turns + scorecard) — the unit
    # behind the default bench duration when no retry-after is stated.
    _EST_CYCLE_SECONDS = 180.0
    # Floor under provider-stated waits (a "try again in 2s" isn't worth
    # un-benching for) and ceiling on backoff (an exhausted daily quota still
    # gets a probe every ~30 min so recovery is noticed the same run).
    _MIN_BENCH_SECONDS = 30.0
    _MAX_BENCH_SECONDS = 1800.0

    def _benched(self, model: str, index: int = 0) -> bool:
        del index  # wall-clock deadlines now; kept for call-site compatibility
        return self._bench.get(model, 0.0) > time.monotonic()

    def _bench_model(self, model: str, index: int, error_text: str = "") -> None:
        """Sit the model out until a wall-clock deadline.

        Honors the provider's OWN stated wait when the error carries one (Groq
        'try again in Xs', Gemini retryDelay, retry-after headers — formats in
        C:\\maistro\\MODEL-LIMITS.md). Otherwise defaults to ``bench_cycles``
        worth of estimated cycle time, DOUBLED per consecutive bench of this
        model — a one-off RPM blip costs one short sit-out, while a drained
        daily quota backs off geometrically instead of burning a probe every
        cycle. The streak resets when the model scores work again.
        """
        streak = self._bench_counts.get(model, 0) + 1
        self._bench_counts[model] = streak
        stated = _parse_retry_after_seconds(error_text)
        if stated is not None:
            seconds = max(stated, self._MIN_BENCH_SECONDS)
            source = "provider retry-after"
        else:
            seconds = self._config.bench_cycles * self._EST_CYCLE_SECONDS * (2 ** (streak - 1))
            source = f"default x{streak}"
        seconds = min(seconds, self._MAX_BENCH_SECONDS)
        self._bench[model] = time.monotonic() + seconds
        self._benched_this_cycle.add(model)  # skip remaining attempts in this cycle
        logger.info(
            "rsi_model_benched",
            model=model,
            cycle=index,
            seconds=round(seconds, 1),
            source=source,
        )

    def _observe_reliability(self, model: str, ok: bool) -> float:
        """EMA per-model reliability: 0.7*prev + 0.3*outcome, starting at 1.0."""
        prev = self._reliability.get(model, 1.0)
        current = round(0.7 * prev + 0.3 * (1.0 if ok else 0.0), 4)
        self._reliability[model] = current
        if ok:
            self._bench_counts.pop(model, None)  # streak ends on real work
        return current

    def _competitors(self, index: int = 1) -> list[Competitor]:
        if self._population is not None:
            return self._genome_roster(index)
        # Empty roster ⇒ a single attempt with the configured model (classic cycle).
        # Benched models sit the cycle out; never filter down to an empty roster.
        static = [c for c in self._config.competitors if not self._benched(c.model, index)]
        return static or self._config.competitors or [Competitor(model=self._config.model or "")]

    def _genome_roster(self, index: int) -> list[Competitor]:
        """Project the population onto this cycle's roster (live evolution).

        Unscored genomes (fresh children awaiting verification-by-work) get
        priority so verification never starves; remaining seats go to the
        fittest. Genomes whose model is benched (transient provider errors) sit
        the cycle out — no eval burned, no stub folded, seat freed. Static
        ``--competitors`` entries still join (they compete but don't evolve).
        Labels are made genome-unique so composites fold back to the exact
        genome that authored the fix.
        """
        from maistro_rsi.evolve_bridge import genome_to_competitor

        genomes = [
            g for g in self._population.list_all() if not self._benched(_entry_model(g), index)
        ]
        unscored = [g for g in genomes if not g.eval_scores]
        scored = sorted(
            (g for g in genomes if g.eval_scores),
            key=lambda g: g.fitness_score or 0.0,
            reverse=True,
        )
        seats = max(1, self._config.roster_size)
        picked = (unscored + scored)[:seats]
        if not picked:
            # NEVER IDLE: every genome's model is benched (the whole roster's
            # provider(s) rate-limited/quota-drained). Rather than no-op the cycle,
            # field a servable cross-provider model.
            model = self._emergency_model(index)
            if model is not None and not self._benched(model, index):
                # A genuinely SERVABLE model: spawn a fresh lineage and persist it —
                # it will do real work, score, and evolve.
                spawned = self._spawn_emergency_genome(model)
                logger.warning(
                    "rsi_local_emergency_spawn",
                    cycle=index,
                    model=model,
                    genome=spawned.id,
                    reason="all roster models benched",
                )
                picked = [spawned]
            elif model is not None:
                # EVERYTHING (roster + emergency pool) is benched: a least-bad
                # transient PROBE. Do NOT persist an unscored lineage — over a long
                # outage that would flood population.db with duplicate emergency
                # genomes and even evict proven scored ones (a transient 429 folds
                # no score, and unscored genomes survive culling). Field a bare
                # competitor whose label maps to no genome, so it never folds back.
                logger.warning(
                    "rsi_local_emergency_probe",
                    cycle=index,
                    model=model,
                    reason="all models benched — transient probe, not persisted",
                )
                self._label_to_genome.clear()
                return [Competitor(model=model, label=f"emergency-probe#{model[:16]}")]
        self._label_to_genome.clear()
        roster: list[Competitor] = []
        for g in picked:
            comp = genome_to_competitor(g)
            comp.label = f"{g.name[:18]}#{g.id[:6]}"
            self._label_to_genome[comp.label] = g.id
            roster.append(comp)
        roster += [c for c in self._config.competitors if not self._benched(c.model, index)]
        return roster or [Competitor(model=self._config.model or "")]

    def _emergency_pool(self) -> list[str]:
        """The never-idle fallback pool (configured ``emergency_models``, else the
        cross-provider default), de-duped with order preserved."""
        pool = list(self._config.emergency_models) or list(_DEFAULT_EMERGENCY_MODELS)
        out: list[str] = []
        for m in pool:
            if m and m not in out:
                out.append(m)
        return out

    def _emergency_model(self, index: int) -> str | None:
        """A SERVABLE model to rescue an all-benched cycle, cloud first:

        1. the most-reliable non-benched model from the emergency pool;
        2. else ``local_fallback_model`` — local hardware cannot rate-limit, so it
           is the floor that keeps a quota-drained run alive (see the field);
        3. else the pool model whose bench expires soonest (least-bad probe) — the
           loop must still try SOMETHING rather than idle.

        ``None`` only when the pool is empty and no local tier is configured.
        """
        pool = self._emergency_pool()
        servable = [m for m in pool if not self._benched(m, index)]
        if servable:
            return max(servable, key=lambda m: self._reliability.get(m, 1.0))
        local = self._config.local_fallback_model
        if local and not self._benched(local, index):
            return local
        if not pool:
            return None
        return min(pool, key=lambda m: self._bench.get(m, 0.0))

    def _spawn_emergency_genome(self, model: str) -> Any:
        """Seed a fresh genome pinned to ``model`` and add it to the population — a
        new lineage on a servable model that persists and evolves, not a
        throwaway. This is the 'we MUST run some models each cycle' guarantee."""
        from maistro_evolve.diversity import _random_genome

        genome = _random_genome([model])
        self._population.add(genome)
        return genome

    def _apply_for_competitor(
        self, competitor: Competitor, objective: str, budget: BudgetTier = BudgetTier.BOUNDED
    ) -> ApplyPatchFn:
        # An injected callable (tests) wins; otherwise build a builders provider
        # carrying this competitor's model + temperature and the slot's objective.
        # A FEATURE (v2.0) slot unlocks a larger turn budget for ambitious work.
        if self._injected_apply is not None:
            return self._injected_apply
        turns = self._config.agent_turns_per_cycle
        if budget is BudgetTier.UNLOCKED:
            turns = max(turns, self._config.feature_agent_turns)
        return make_builders_apply_patch(
            objective,
            model=competitor.model or self._config.model,
            temperature=competitor.temperature,
            reasoning_effort=competitor.reasoning_effort,
            system_prompt=competitor.prompt,
            max_agent_turns=turns,
            isolation=self._config.isolation,
            image=self._config.sandbox_image,
        )

    def _changed_files(self, cwd: Path) -> list[str]:
        status = _git(cwd, "status", "--porcelain")
        return [ln[3:].strip() for ln in status.stdout.splitlines() if ln.strip()]

    def _load_saved_patches(self) -> None:
        """Resume from a prior run: reapply all saved patches to the baseline.

        When a run is interrupted or restarted (same REPORT_DIR), patches
        exported to REPORT_DIR/export/*.patch are applied to the fresh baseline
        so the new run picks up where the old one left off. This preserves all
        promotions across restarts/crashes.
        """
        if not self._config.export_patches:
            return  # no export dir configured; nothing to restore
        export_dir = Path(self._config.export_patches)
        if not export_dir.exists():
            return  # no prior exports yet
        patches = sorted(export_dir.glob("*.patch"))
        if not patches:
            return
        logger.info(
            "rsi_local_resume_patches",
            count=len(patches),
            export_dir=str(export_dir),
        )
        applied = 0
        for patch_file in patches:
            # Plain `git apply` (NOT --reject) is ATOMIC: a patch that doesn't
            # apply cleanly writes NOTHING and leaves the tree untouched. This is
            # essential on resume — `--reject` would write every clean hunk and
            # drop `.rej` files for the rest before returning non-zero, and those
            # partial changes + `.rej` files would then be swept into the resume
            # commit below and poison the baseline. It stays idempotent, too:
            # an already-applied patch simply fails cleanly and is skipped.
            result = _git(
                self._baseline,
                "apply",
                str(patch_file),
                check=False,
            )
            if result.returncode == 0:
                applied += 1
                logger.info("rsi_local_patch_applied", patch=patch_file.name)
            else:
                # Patch already applied (or conflicts) — nothing was written (atomic
                # apply), so the tree stays clean. Log and continue. The baseline may
                # be ahead of these patches if a prior run completed cycles that
                # hadn't been exported yet.
                logger.info(
                    "rsi_local_patch_skip",
                    patch=patch_file.name,
                    note="already applied or conflict",
                )
        # CRITICAL: `git apply` only touches the working tree — it never moves
        # `baseline_branch`. Every cycle's variant is created via `git worktree
        # add <dir> baseline_branch` (checks out the BRANCH REF, not this dirty
        # working tree), so without this commit the resumed patches are
        # invisible to every subsequent cycle: they'd sit here uncommitted while
        # cycles silently rebuild from the pristine pre-resume commit. Committing
        # also self-heals `export_promotions` (ranges from `_start_ref`, set
        # before this method runs), so the next checkpoint's rolling export
        # correctly includes the resumed history again instead of only this
        # launch's own new commits.
        if applied and self._changed_files(self._baseline):
            _git(self._baseline, "add", "-A")
            _git(
                self._baseline,
                "commit",
                "-q",
                "--no-verify",
                "-m",
                f"resume: reapply {applied} saved patch(es)",
            )
            self._non_promotion_commits += 1
            logger.info("rsi_local_resume_committed", patches=applied)

    def _setup_baseline(self) -> None:
        work_root = Path(self._config.work_root)
        work_root.mkdir(parents=True, exist_ok=True)
        if self._baseline.exists():
            raise RuntimeError(f"work root already has a baseline: {self._baseline}")
        # Local clone — never touches the source repo's branches or working tree.
        _git(work_root, "clone", "--quiet", str(Path(self._config.repo_path).resolve()), "baseline")
        _git(self._baseline, "checkout", "-q", "-B", self._config.baseline_branch)
        # Remember where the baseline started so we can export exactly the
        # promotion commits (start_ref..baseline), not the repo's whole history.
        self._start_ref = _git(self._baseline, "rev-parse", "HEAD").stdout.strip()
        logger.info(
            "rsi_local_baseline_ready",
            baseline=str(self._baseline),
            branch=self._config.baseline_branch,
        )

    def _run_variant(
        self,
        index: int,
        seq: int,
        competitor: Competitor,
        objective: str,
        budget: BudgetTier = BudgetTier.BOUNDED,
        kind: ImprovementKind = ImprovementKind.DOC,
    ) -> _VariantResult:
        """Run one competitor in its own worktree off the baseline and score it.

        Leaves the committed worktree/branch in place for the cycle to merge and
        clean up. Never raises — an agent/LLM error becomes a non-accepted result
        so one bad competitor can't sink the whole cycle.
        """
        branch = f"rsi/cycle-{index}-v{seq}-{uuid.uuid4().hex[:6]}"
        cdir = Path(self._config.work_root) / f"cycle-{index}-v{seq}"
        _git(
            self._baseline,
            "worktree",
            "add",
            "-q",
            "-b",
            branch,
            str(cdir),
            self._config.baseline_branch,
        )
        r = _VariantResult(branch=branch, cycle_dir=cdir, label=competitor.label, kind=kind)
        try:
            apply_fn = self._apply_for_competitor(competitor, objective, budget)
            asyncio.run(apply_fn(LocalSandbox(cdir), str(cdir), None))
            _git(cdir, "add", "-A")
            r.changed_files = self._changed_files(cdir)
            if not r.changed_files:
                r.note = "no change"
                return r
            r.changed = True
            r.files_touched = len(r.changed_files)
            _git(
                cdir,
                "commit",
                "-q",
                "--no-verify",
                "-m",
                f"RSI cycle {index} [{competitor.label}]: {objective[:50]}",
            )
            if self._config.use_fitness:
                (
                    r.accepted,
                    r.composite,
                    r.note,
                    r.tests_passed,
                    r.regression_judge_score,
                    r.trace,
                ) = self._fitness_decision(index, cdir, r.changed_files, target=objective)
            else:
                r.tests_passed = self._run_tests(cdir)
                r.accepted = r.tests_passed
                r.note = "" if r.tests_passed else "test command failed"
        except Exception as exc:
            r.errored = True
            if _is_transient_provider_error(str(exc)):
                # Capacity, not fitness: bench the model so it sits out a few
                # cycles, and mark the result transient so live evolution folds
                # NO sample for this genome (sitting out is neutral). Expected
                # under load, so info-level and no traceback.
                r.note = f"transient: {exc}"
                self._bench_model(competitor.model, index, error_text=str(exc))
                logger.info(
                    "rsi_local_variant_transient",
                    index=index,
                    competitor=competitor.label,
                    model=competitor.model or self._config.model,
                    error=str(exc),
                )
            else:
                # A non-transient variant fault (bad apply, git failure, fitness
                # crash) is a REAL error, not the agent quietly declining to
                # change anything. Surface it with a traceback so it can never
                # masquerade as "agent made no change" in the cycle summary.
                r.note = f"variant errored: {exc}"
                logger.warning(
                    "rsi_local_variant_error",
                    index=index,
                    competitor=competitor.label,
                    error=str(exc),
                    exc_info=True,
                )
        # note is logged unconditionally: an errored/transient variant otherwise
        # looks identical to a genuine no-op (both changed=False, accepted=False).
        logger.info(
            "rsi_local_variant",
            index=index,
            competitor=competitor.label,
            accepted=r.accepted,
            composite=r.composite,
            changed=r.changed,
            errored=r.errored,
            note=r.note,
        )
        return r

    def _apply_to_merge(self, merge_dir: Path, variant: _VariantResult) -> bool:
        patch = _git(
            self._baseline, "diff", f"{self._config.baseline_branch}..{variant.branch}"
        ).stdout
        applied = bool(patch.strip()) and _git_apply(merge_dir, patch)
        logger.info(
            "rsi_local_merge_apply",
            variant=variant.label,
            applied=applied,
            patch_lines=len(patch.splitlines()),
        )
        return applied

    def _run_cycle(self, index: int) -> CycleOutcome:
        self._benched_this_cycle.clear()  # reset in-cycle benching tracker
        target = self._target_for_cycle(index)
        slots = self._cycle_slots(index)
        competitors = self._competitors(index)
        variants: list[_VariantResult] = []
        created: list[tuple[str, Path]] = []
        try:
            for seq, comp in enumerate(competitors, 1):
                # Skip if this model was benched during this cycle — don't waste attempts
                if (comp.model or self._config.model) in self._benched_this_cycle:
                    continue
                # Spread competitors across the scout's shortlist slots; with more
                # competitors than slots they double up (competitive on one item).
                slot_idx = (seq - 1) % len(slots)
                objective, budget, kind = slots[slot_idx]
                r = self._run_variant(index, seq, comp, objective, budget, kind)
                r.slot = slot_idx
                r.model = comp.model or self._config.model or ""
                r.genome_id = self._label_to_genome.get(comp.label)
                variants.append(r)
                created.append((r.branch, r.cycle_dir))

            # Live evolution: fold this cycle's REAL composites back into the
            # genomes that authored them, then evolve the population. Runs before
            # promotion selection so a cycle with no accepted variant still
            # teaches (a rejected fix's 0.0 is genuine evidence).
            if self._population is not None:
                self._live_evolution_step(index, variants)

            accepted = sorted(
                (r for r in variants if r.accepted), key=lambda r: r.composite, reverse=True
            )
            if not accepted:
                changed_any = any(r.changed for r in variants)
                errored = [r for r in variants if r.errored]
                if changed_any:
                    # A variant produced a diff but no variant was accepted.
                    note = next(
                        (r.note for r in variants if r.changed and r.note),
                        "rejected by fitness",
                    )
                elif errored:
                    # Every variant either crashed or no-op'd, and at least one
                    # crashed — report the fault, not a misleading "no change".
                    note = f"all {len(variants)} variant(s) failed; first error: {errored[0].note}"
                    logger.warning(
                        "rsi_local_cycle_all_variants_errored",
                        index=index,
                        errored=len(errored),
                        total=len(variants),
                        first_error=errored[0].note,
                    )
                else:
                    note = "agent made no change"
                return CycleOutcome(
                    index,
                    changed=changed_any,
                    tests_passed=any(r.tests_passed for r in variants),
                    promoted=False,
                    files_touched=(variants[0].files_touched if variants else 0),
                    target=target,
                    note=note,
                )

            promote_branch, composite, files, kept_n, judge_score = self._select_and_merge(
                index, target, accepted, created
            )
            _git(self._baseline, "merge", "--ff-only", promote_branch)
            promoted_sha = _git(self._baseline, "rev-parse", "HEAD").stdout.strip()
            self._record_scout_success(self._last_scout_model)
            # Baseline advanced — recompute coverage/uncovered/spec-gaps next
            # cycle (a promotion may have covered lines or claimed AC gaps).
            self._baseline_cov = None
            self._baseline_missing = {}
            self._spec_gaps = None
            note = (
                f"tournament: {len(competitors)} competitor(s), {len(accepted)} passed, "
                f"kept {kept_n} (composite={composite})"
            )
            self._annotate_promotion(
                promoted_sha, index, target, accepted[0], composite, files, note
            )
            logger.info(
                "rsi_local_cycle_promoted",
                index=index,
                target=target,
                competitors=len(competitors),
                passed=len(accepted),
                kept=kept_n,
                composite=composite,
                sha=promoted_sha,
            )
            return CycleOutcome(
                index,
                changed=True,
                tests_passed=True,
                promoted=True,
                files_touched=files,
                target=target,
                composite=composite,
                note=note,
                sha=promoted_sha,
                kind=accepted[0].kind,
                regression_judge_score=judge_score,
            )
        finally:
            for branch, worktree_dir in created:
                _git(
                    self._baseline, "worktree", "remove", "--force", str(worktree_dir), check=False
                )
                _git(self._baseline, "branch", "-D", branch, check=False)

    def _live_evolution_step(self, index: int, variants: list[_VariantResult]) -> None:
        """The unified loop's between-cycle evolution — real work IS the evaluation.

        Folds each genome-authored variant's composite into its genome (EMA;
        a rejected fix's 0.0 is genuine evidence, an agent error is a stub, a
        TRANSIENT provider error folds nothing — the model sat out). Same-slot
        variants fought over the same scout item, so they settle it on the Elo
        ladder. Then fitness → cull → breed → a hyper-mutator child for the top
        genome, which joins UNVERIFIED: its verification is the next cycle's
        actual work. Never raises — evolution must not sink the work loop.
        """
        try:
            # Reliability first: every attempt teaches about its MODEL —
            # transient provider failures decay it, anything that reached
            # scoring recovers it (including static competitors' models).
            for v in variants:
                if v.model:
                    self._observe_reliability(v.model, ok=not v.note.startswith("transient:"))

            self._fold_cycle_scores(variants)
            self._record_cycle_battles(variants)
            scored = self._refit_cull_breed()
            # Guided mutation: the hyper-mutator proposes a child for the top
            # genome, grounded in lineage + the operator goal.
            if scored:
                self._hyper_propose(scored[0])

            logger.info(
                "rsi_live_evolution",
                index=index,
                population=len(self._population.list_all()),
                benched=[m for m in self._bench if self._benched(m)],
            )
        except Exception as exc:
            logger.warning("rsi_live_evolution_error", index=index, error=str(exc))

    def _fold_cycle_scores(self, variants: list[_VariantResult]) -> None:
        """Fold each genome-authored variant's real composite into its genome
        (EMA). A transient sit-out folds nothing; an agent error folds a stub."""
        from maistro_evolve.cycle import EvolutionCycle

        store = self._population
        by_id = {g.id: g for g in store.list_all()}
        for v in variants:
            genome = by_id.get(v.genome_id or "")
            if genome is None or v.note.startswith("transient:"):
                continue  # static competitor, culled genome, or sat out
            stub = v.note.startswith("variant errored")
            EvolutionCycle._fold_score(genome, "code_rsi", v.composite, stub, 0.5)
            genome.updated_at = datetime.now(UTC).isoformat()
            store.add(genome)

    def _record_cycle_battles(self, variants: list[_VariantResult]) -> None:
        """Same-slot variants attempted the SAME scout item — a fair Elo battle."""
        if self._elo is None:
            return
        by_id = {g.id: g for g in self._population.list_all()}
        fought = [
            v for v in variants if v.genome_id in by_id and not v.note.startswith("transient:")
        ]
        for i, a in enumerate(fought):
            for b in fought[i + 1 :]:
                if a.slot == b.slot:
                    self._elo.record_battle(
                        benchmark="code_rsi",
                        genome_a_id=a.genome_id,
                        genome_b_id=b.genome_id,
                        score_a=a.composite,
                        score_b=b.composite,
                    )
        for v in fought:
            elo = self._elo.get_avg_elo(v.genome_id)
            if elo > 0:
                by_id[v.genome_id].harness_params["avg_elo"] = elo

    def _refit_cull_breed(self) -> list[Any]:
        """Fitness (reliability-multiplied) → cull the weakest → breed one child.

        Fitness is MULTIPLIED by the genome's model reliability: the same slot
        settings on a flaky provider are worth less than on a dependable one, so
        evolution re-tries winning strategies on more reliable carriers. Unscored
        children are never culled — they haven't had their verification cycle.
        Returns the surviving scored genomes, fittest first.
        """
        from maistro_evolve.crossover import crossover_and_mutate
        from maistro_evolve.fitness import compute_fitness

        store = self._population
        everyone = store.list_all()
        for g in everyone:
            if g.eval_scores:
                reliability = self._reliability.get(_entry_model(g), 1.0)
                g.fitness_score = compute_fitness(g, everyone).total * reliability
                g.harness_params["model_reliability"] = reliability
                store.add(g)

        scored = sorted(
            (g for g in store.list_all() if g.fitness_score is not None),
            key=lambda g: g.fitness_score or 0.0,
            reverse=True,
        )
        max_pop = max(4, self._config.roster_size * 2)
        excess = min(len(store.list_all()) - max_pop, len(scored))
        if excess > 0:
            for g in scored[-excess:]:
                store.remove(g.id)
            scored = scored[:-excess]

        # Breed: one crossover child of the two fittest, models constrained to
        # what the population actually runs (no drift off the roster).
        if len(scored) >= 2 and len(store.list_all()) < max_pop:
            models = sorted({_entry_model(g) for g in store.list_all()})
            store.add(crossover_and_mutate(scored[0], scored[1], 0.3, models=models))
        return scored

    def _hyper_propose(self, top: Any) -> None:
        """Ask the hyper-mutator for one guided child of ``top``; it joins the
        population UNVERIFIED and earns its scores in the next real cycle."""
        from maistro_bootstrap.builders.responses_callable import ResponsesAPICallable
        from maistro_evolve.hyper_mutator import (
            entry_node,
            propose_fixer_candidates,
            slot_lineage,
            spawn_fixer_challenger,
        )

        node = entry_node(top)
        if node is None or node.fixer is None:
            return
        fixer = node.fixer  # narrowed local — mypy keeps this non-None inside propose()
        callable_ = ResponsesAPICallable(
            model=self._config.scout_model or self._config.model, timeout=300.0
        )

        async def llm(prompt: str) -> str:
            result = await asyncio.to_thread(callable_, [{"role": "user", "content": prompt}])
            content = result.get("content", "") if isinstance(result, dict) else result
            return content if isinstance(content, str) else str(content)

        async def propose() -> list[Any]:
            return await propose_fixer_candidates(
                fixer,
                "code_rsi",
                top.eval_scores.get("code_rsi", 0.0),
                llm,
                1,
                lineage=slot_lineage(top, self._population.list_all()),
                goal=self._config.evolve_goal,
            )

        for candidate in asyncio.run(propose())[:1]:
            child = spawn_fixer_challenger(top, candidate)
            self._population.add(child)
            logger.info("rsi_live_hyper_child", parent=top.name, child=child.name)

    def _population_summary(self) -> dict[str, Any]:
        """Snapshot the live population for checkpoint observability: WORK
        (promotions) is already in every report; this is whether the run is
        actually LEARNING — population size, generation spread, the fittest
        genomes' settings, per-model reliability, who's sitting out, and the
        newest lineage memory the hyper-mutator wrote. Purely descriptive:
        reading this never changes the run.
        """
        from maistro_evolve.hyper_mutator import entry_node

        genomes = self._population.list_all()
        generations = dict(sorted(Counter(g.generation for g in genomes).items()))
        scored = sorted(
            (g for g in genomes if g.fitness_score is not None),
            key=lambda g: g.fitness_score or 0.0,
            reverse=True,
        )
        top_genomes = []
        for g in scored[:3]:
            node = entry_node(g)
            fixer = node.fixer if node else None
            top_genomes.append(
                {
                    "name": g.name,
                    "generation": g.generation,
                    "fitness": g.fitness_score,
                    "code_rsi": g.eval_scores.get("code_rsi"),
                    "model": _entry_model(g),
                    "tdd_rigor": fixer.tdd_rigor if fixer else None,
                    "test_style": fixer.test_style.value if fixer else None,
                }
            )
        memory: dict[str, str] = {}
        if scored:
            node = entry_node(scored[0])
            fixer = node.fixer if node else None
            if fixer and fixer.learned_successes:
                memory["learned_successes"] = fixer.learned_successes[:160]
            if fixer and fixer.learned_failures:
                memory["learned_failures"] = fixer.learned_failures[:160]
        return {
            "population_size": len(genomes),
            "generations": generations,
            "top_genomes": top_genomes,
            "reliability": dict(self._reliability),
            "benched_models": [m for m in self._bench if self._benched(m)],
            "memory": memory,
        }

    def _select_and_merge(
        self,
        index: int,
        target: str,
        accepted: list[_VariantResult],
        created: list[tuple[str, Path]],
    ) -> tuple[str, float, int, int, float | None]:
        """Combine passing candidates (highest-composite first). Returns
        ``(promote_branch, composite, files_touched, kept_count, regression_judge_score)``.

        One winner promotes its branch directly (identical to the classic cycle).
        A 2+ combination keeps only non-conflicting diffs (complementary), is
        re-scored, and falls back to the single top candidate if it regresses.
        """
        if len(accepted) == 1:
            top = accepted[0]
            return top.branch, top.composite, top.files_touched, 1, top.regression_judge_score

        merge_branch = f"rsi/cycle-{index}-m-{uuid.uuid4().hex[:6]}"
        merge_dir = Path(self._config.work_root) / f"cycle-{index}-m"
        _git(
            self._baseline,
            "worktree",
            "add",
            "-q",
            "-b",
            merge_branch,
            str(merge_dir),
            self._config.baseline_branch,
        )
        created.append((merge_branch, merge_dir))
        kept = greedy_merge(accepted, lambda r: self._apply_to_merge(merge_dir, r))
        if len(kept) <= 1:
            # 1 kept: every candidate collided into one region — the top-scored
            # one won. 0 kept: nothing applied cleanly onto the merge worktree —
            # fall back to the top candidate, which is committed and validated.
            top = kept[0] if kept else accepted[0]
            return top.branch, top.composite, top.files_touched, 1, top.regression_judge_score
        changed_files = self._changed_files(merge_dir)
        _git(merge_dir, "add", "-A")
        _git(
            merge_dir,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"RSI cycle {index}: merged {len(kept)} complementary fix(es) of {target}",
        )
        if self._config.use_fitness:
            m_ok, m_comp, reason, _tp, m_judge, _trace = self._fitness_decision(
                index, merge_dir, changed_files
            )
            if not m_ok:
                logger.info("rsi_local_merge_regressed", index=index, reason=reason)
                return (
                    kept[0].branch,
                    kept[0].composite,
                    kept[0].files_touched,
                    1,
                    kept[0].regression_judge_score,
                )
            return merge_branch, m_comp, len(changed_files), len(kept), m_judge
        # No fitness: each kept candidate passed its own tests in isolation, but
        # the COMBINATION was never tested — two non-conflicting patches can still
        # interact and break the suite. Retest the merged worktree; fall back to
        # the top candidate (known-good on its own) if the combination regresses.
        if self._run_tests(merge_dir):
            return (
                merge_branch,
                kept[0].composite,
                len(changed_files),
                len(kept),
                kept[0].regression_judge_score,
            )
        logger.info("rsi_local_merge_untested_regressed", index=index)
        return (
            kept[0].branch,
            kept[0].composite,
            kept[0].files_touched,
            1,
            kept[0].regression_judge_score,
        )

    def _judge_regression(self, diff_text: str, target: str) -> tuple[float, str]:
        """Second-opinion LLM regression check — see regression_judge.py. Never
        raises: an unavailable/erroring gateway must not block promotion."""
        try:
            from maistro_bootstrap.builders.responses_callable import ResponsesAPICallable
            from maistro_rsi.regression_judge import judge_regression

            llm = ResponsesAPICallable(model=self._config.scout_model or self._config.model)
            return judge_regression(diff_text, target, llm)
        except Exception:
            return 0.7, "judge unavailable"

    def _fitness_decision(
        self, index: int, cycle_dir: Path, changed_files: list[str], *, target: str = ""
    ) -> tuple[bool, float, str, bool, float | None, dict[str, Any]]:
        """Build the multi-signal Scorecard for the candidate and return
        (accepted, composite, reject_reason, tests_passed, regression_judge_score,
        trace). Logs explain(). The judge score (None if the judge never ran)
        survives past its pass/fail gate so the checkpoint-time RLPHD reviewer can
        use it as prediction evidence, not just the boolean veto. ``trace`` is a
        compact per-gate/reward bundle for the commit's git-notes record."""
        from maistro_rsi.candidate_fitness import evaluate_candidate

        scorecard = evaluate_candidate(
            cycle_dir,
            changed_files,
            test_command=self._config.test_command,
            coverage_source=self._config.coverage_source,
            coverage_pytest_args=self._config.coverage_pytest_args,
            baseline_coverage=self._baseline_coverage(),
            baseline_ref=self._config.baseline_branch,
            timeout=self._config.test_timeout,
            regression_judge_fn=self._judge_regression if self._config.regression_judge else None,
            target=target,
        )
        logger.info(
            "rsi_local_scorecard",
            index=index,
            accepted=scorecard.accepted,
            composite=scorecard.composite,
            explain="\n" + scorecard.explain(),
        )
        tests_passed = next((g.passed for g in scorecard.gates if g.name == "tests_pass"), False)
        reason = next((f"{g.name}: {g.reason}" for g in scorecard.gates if not g.passed), "")
        judge_raw = next(
            (g.detail.get("score") for g in scorecard.gates if g.name == "no_flagged_regression"),
            None,
        )
        # detail is dict[str, object]; the regression judge stores a float score.
        judge_score = float(judge_raw) if isinstance(judge_raw, int | float) else None
        mut_raw = next(
            (g.detail.get("score") for g in scorecard.gates if g.name == "tests_pin_behavior"),
            None,
        )
        trace: dict[str, Any] = {
            "gates": {g.name: g.passed for g in scorecard.gates},
            "composite": scorecard.composite,
            "mutation_score": float(mut_raw) if isinstance(mut_raw, int | float) else None,
        }
        return (
            scorecard.accepted,
            scorecard.composite,
            reason,
            tests_passed,
            judge_score,
            trace,
        )

    def _annotate_promotion(
        self,
        sha: str,
        index: int,
        target: str,
        top: _VariantResult,
        composite: float,
        files: int,
        summary: str,
    ) -> None:
        """Attach a git-notes trace record to a just-promoted commit (SPEC: the
        HORIZON-style acceptance/reward substrate). Best-effort — write_trace_note
        never raises — so annotating the ratchet can never fail a landed promotion.
        The record makes the promotion reconstructable from git alone: its verdict
        (per-gate pass/fail) and reward vector (pass/composite/mutation/judge)."""
        from maistro_rsi.trace_notes import RewardVector, TraceNote, write_trace_note

        gates = top.trace.get("gates") or {"tests_pass": top.tests_passed}
        trace_note = TraceNote(
            cycle=index,
            target=target,
            accepted=True,
            kind=top.kind.value,
            model=top.model or self._config.model or "",
            files_touched=files,
            reward=RewardVector(
                delta_pass=1.0 if top.tests_passed else 0.0,
                composite=composite,
                mutation_score=top.trace.get("mutation_score"),
                regression_judge=top.regression_judge_score,
            ),
            gates={str(k): bool(v) for k, v in gates.items()},
            note=summary,
        )
        write_trace_note(self._baseline, sha, trace_note)

    def _run_tests(self, cycle_dir: Path) -> bool:
        # shell=True: the test command is operator-supplied config, not agent input.
        proc = subprocess.run(  # nosemgrep
            self._config.test_command,
            shell=True,  # nosemgrep
            cwd=str(cycle_dir),
            capture_output=True,
            text=True,
            timeout=self._config.test_timeout,
        )
        if proc.returncode != 0:
            logger.info("rsi_local_tests_failed", tail=(proc.stdout + proc.stderr)[-500:])
        return proc.returncode == 0

    def run(self) -> LocalRsiResult:
        self._setup_baseline()
        self._load_saved_patches()  # resume from a prior run by reapplying saved patches
        # Review starts AFTER any resume commit: a resumed patch is already-
        # decided history from a prior run, not a fresh scored promotion — it
        # must never be re-reviewed (it has no CycleOutcome/features to score).
        self._last_reviewed_ref = _git(self._baseline, "rev-parse", "HEAD").stdout.strip()
        result = LocalRsiResult(baseline_dir=str(self._baseline))
        for index in range(1, self._config.max_cycles + 1):
            logger.info("rsi_local_cycle_start", index=index, of=self._config.max_cycles)
            try:
                outcome = self._run_cycle(index)
            except Exception as exc:  # one bad cycle shouldn't kill the run
                logger.warning("rsi_local_cycle_error", index=index, error=str(exc))
                outcome = CycleOutcome(
                    index, changed=False, tests_passed=False, promoted=False, note=f"error: {exc}"
                )
            result.cycles.append(outcome)
            # Interim checkpoint every N cycles: a progress report + a refreshed
            # export of everything promoted so far. The baseline is not touched —
            # the loop keeps ratcheting from here.
            if (
                self._config.report_dir
                and self._config.report_every
                and index % self._config.report_every == 0
                and index != self._config.max_cycles
            ):
                self._write_checkpoint(result, label=f"cycle {index}")
        logger.info(
            "rsi_local_loop_complete", promotions=result.promotions, cycles=len(result.cycles)
        )
        # A final report always closes out a reported run (captures the last,
        # possibly-partial window).
        if self._config.report_dir:
            self._write_checkpoint(result, label="final")
        if self._config.export_patches and result.promotions:
            n = self.export_promotions(Path(self._config.export_patches))
            logger.info("rsi_local_exported", patches=n, dest=self._config.export_patches)
        if self._population is not None:
            logger.info("rsi_live_final_summary", **self._population_summary())
        return result

    def _write_checkpoint(self, result: LocalRsiResult, *, label: str) -> None:
        """Write a progress report (markdown + JSON) and refresh the rolling,
        complete patch export under ``report_dir``.

        Never raises: a checkpoint is observability for a long run, so a reporting
        hiccup must never abort the loop that is producing real promotions.
        """
        try:
            report_dir = Path(self._config.report_dir or ".")
            report_dir.mkdir(parents=True, exist_ok=True)
            md, data = build_checkpoint_report(
                result.cycles,
                total_planned=self._config.max_cycles,
                baseline_dir=str(self._baseline),
                window=self._config.report_every or len(result.cycles),
                label=label,
                population_summary=(
                    self._population_summary() if self._population is not None else None
                ),
            )
            slug = label.replace(" ", "-")
            (report_dir / f"checkpoint-{slug}.md").write_text(md, encoding="utf-8")
            (report_dir / f"checkpoint-{slug}.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            self._review_promotions(result, report_dir)
            self._check_persistence_integrity(result, label)
            # Refresh a rolling, COMPLETE export of everything promoted so far, so
            # an interrupted long run stays harvestable from its last checkpoint.
            # Always clear+rewrite — even at zero promotions — so a reused report
            # dir can't leave stale patches/manifest that `harvest` would apply.
            # Runs AFTER _review_promotions so a just-reverted promotion is never
            # exported as if it were still kept.
            self.export_promotions(report_dir / "export", clear=True)
            logger.info(
                "rsi_local_checkpoint",
                label=label,
                cycles=len(result.cycles),
                promotions=result.promotions,
                dir=str(report_dir),
            )
        except Exception as exc:
            logger.warning("rsi_local_checkpoint_error", label=label, error=str(exc))

    def _review_promotions(self, result: LocalRsiResult, report_dir: Path) -> None:
        """Checkpoint-time RLPHD gate (promotion_review.py / SPEC-248): any
        promotion since the last review pass whose predicted approval
        confidence falls below its action-class's adaptive theta is REVERTED
        NOW — so nothing keeps building on top of it — but the original patch
        is saved to ``report_dir/flagged/``, queued for a human decision that
        feeds straight back into the same dual-signal, surprise-weighted
        update RLPHD already uses for tool-call approval.

        A promotion a LATER commit already depends on (touched the same file)
        is never reverted: supersession makes a clean revert impossible
        without unwinding real work, so it's observed and skipped, not
        silently ignored. Never raises: a reviewer hiccup must not abort a
        long run's real work.
        """
        if not self._config.promotion_review or self._last_reviewed_ref is None:
            return
        try:
            from maistro_rsi.promotion_review import RlphdStateStore

            revs = _git(
                self._baseline,
                "rev-list",
                "--reverse",
                f"{self._last_reviewed_ref}..{self._config.baseline_branch}",
            ).stdout.split()
            if not revs:
                return
            by_sha = {c.sha: c for c in result.cycles if c.promoted and c.sha}
            files_by_sha: dict[str, set[str]] = {}
            for sha in revs:
                names = [
                    ln.strip()
                    for ln in _git(
                        self._baseline, "show", "--name-only", "--pretty=format:", sha
                    ).stdout.splitlines()
                    if ln.strip()
                ]
                files_by_sha[sha] = set(names)

            state = RlphdStateStore(report_dir / "rlphd_state.json")
            for i, sha in enumerate(revs):
                outcome = by_sha.get(sha)
                if outcome is None:
                    continue  # not a scored promotion (e.g. a resume commit)
                later_files: set[str] = set()
                for later_sha in revs[i + 1 :]:
                    later_files |= files_by_sha.get(later_sha, set())
                superseded = bool(files_by_sha[sha] & later_files)
                self._review_one_promotion(outcome, sha, superseded, state, report_dir)
            self._last_reviewed_ref = _git(
                self._baseline, "rev-parse", self._config.baseline_branch
            ).stdout.strip()
        except Exception as exc:
            logger.warning("rsi_local_review_error", error=str(exc))

    def _review_one_promotion(
        self,
        outcome: CycleOutcome,
        sha: str,
        superseded: bool,
        state: Any,
        report_dir: Path,
    ) -> None:
        """One commit's RLPHD verdict: keep, observe-but-skip (superseded), or
        revert-and-flag. Split out of _review_promotions to keep that method's
        branching within the project's complexity budget."""
        from maistro_rsi.promotion_review import (
            PendingReview,
            action_class_for,
            extract_features,
            flag_for_review,
            now_iso,
            save_kept_review,
        )

        action_class = action_class_for(outcome.kind)
        features = extract_features(
            regression_judge_score=outcome.regression_judge_score,
            composite=outcome.composite,
            kind=outcome.kind,
        )
        p, theta = state.predict(action_class, features)
        if superseded:
            logger.info(
                "rsi_local_review_superseded",
                sha=sha,
                index=outcome.index,
                predicted_p=p,
                theta=theta,
                note="later work depends on this file — cannot cleanly revert",
            )
            return
        if p >= theta:
            kept_review = PendingReview(
                sha=sha,
                index=outcome.index,
                target=outcome.target,
                kind=outcome.kind.value,
                action_class=action_class,
                features=features,
                predicted_p=p,
                theta=theta,
                flagged_at=now_iso(),
                note=f"auto-kept (p={p:.3f} >= theta={theta:.3f}); composite={outcome.composite} judge_score={outcome.regression_judge_score}",
            )
            save_kept_review(
                report_dir / "kept", kept_review, _git(self._baseline, "show", sha).stdout
            )
            logger.info(
                "rsi_local_review_kept", sha=sha, index=outcome.index, predicted_p=p, theta=theta
            )
            return
        patch_text = _git(self._baseline, "show", sha).stdout
        revert_result = _git(self._baseline, "revert", "--no-edit", sha, check=False)
        if revert_result.returncode != 0:
            _git(self._baseline, "revert", "--abort", check=False)
            logger.warning(
                "rsi_local_review_revert_failed",
                sha=sha,
                index=outcome.index,
                error=revert_result.stderr.strip(),
            )
            return
        revert_sha = _git(self._baseline, "rev-parse", "HEAD").stdout.strip()
        # Both the original promotion and its own revert commit are "nothing
        # net happened" — exclude both from the harvestable export, and count
        # the revert as a real, non-promotion commit so the persistence
        # self-check doesn't false-alarm on it.
        self._excluded_from_export.add(sha)
        self._excluded_from_export.add(revert_sha)
        self._non_promotion_commits += 1
        review = PendingReview(
            sha=sha,
            index=outcome.index,
            target=outcome.target,
            kind=outcome.kind.value,
            action_class=action_class,
            features=features,
            predicted_p=p,
            theta=theta,
            flagged_at=now_iso(),
            note=f"composite={outcome.composite} judge_score={outcome.regression_judge_score}",
        )
        flag_for_review(report_dir / "flagged", review, patch_text)
        logger.warning(
            "rsi_local_review_reverted",
            sha=sha,
            index=outcome.index,
            target=outcome.target,
            predicted_p=p,
            theta=theta,
            note="reverted pending human review — patch saved, not discarded",
        )

    def _check_persistence_integrity(self, result: LocalRsiResult, label: str) -> None:
        """Trust-but-verify: the in-memory promotion count must match the actual
        git history on ``baseline_branch``. A mismatch means the persistence
        machinery (patch resume, worktree merges) silently diverged from what the
        loop believes it promoted — exactly the failure mode a resumed-patch
        commit gap once caused. Logs loudly rather than halting: an operator
        should investigate, but a reporting check must never abort real work."""
        if self._start_ref is None:
            return
        try:
            actual = int(
                _git(
                    self._baseline,
                    "rev-list",
                    "--count",
                    f"{self._start_ref}..{self._config.baseline_branch}",
                ).stdout.strip()
            )
        except (RuntimeError, ValueError):
            return
        expected = result.promotions + self._non_promotion_commits
        if actual != expected:
            logger.error(
                "rsi_local_persistence_mismatch",
                label=label,
                recorded_promotions=result.promotions,
                non_promotion_commits=self._non_promotion_commits,
                actual_commits=actual,
                note=(
                    "git history on baseline_branch diverged from the in-memory "
                    "promotion count — a prior run's work may not be reaching the "
                    "committed baseline. Investigate before trusting this run's "
                    "export/resume state."
                ),
            )

    def export_promotions(self, dest: Path, *, clear: bool = False) -> int:
        """Export each promotion commit (start_ref..baseline) as a git-am-able
        patch plus a manifest.json mapping patch -> edited file, for the harvester
        to open PRs grouped by file. Returns the number of patches written.

        ``clear`` first removes any stale ``*.patch``/manifest from a prior write,
        so a rolling checkpoint export always reflects exactly the current set.
        """
        dest.mkdir(parents=True, exist_ok=True)
        if clear:
            for stale in dest.glob("*.patch"):
                stale.unlink()
            (dest / "manifest.json").unlink(missing_ok=True)
        rng = f"{self._start_ref}..{self._config.baseline_branch}"
        revs = [
            sha
            for sha in _git(self._baseline, "rev-list", "--reverse", rng).stdout.split()
            if sha not in self._excluded_from_export
        ]
        manifest: list[dict[str, str]] = []
        for i, sha in enumerate(revs, 1):
            names = [
                ln.strip()
                for ln in _git(
                    self._baseline, "show", "--name-only", "--pretty=format:", sha
                ).stdout.splitlines()
                if ln.strip()
            ]
            subject = _git(self._baseline, "show", "-s", "--pretty=format:%s", sha).stdout.strip()
            patch_name = f"{i:04d}-{sha[:8]}.patch"
            patch = _git(self._baseline, "format-patch", "-1", "--stdout", sha).stdout
            (dest / patch_name).write_text(patch, encoding="utf-8")
            src = next((n for n in names if n.endswith(".py")), names[0] if names else "")
            manifest.append({"patch_file": patch_name, "file": src, "subject": subject})
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return len(manifest)
