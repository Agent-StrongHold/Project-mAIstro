"""Agent loop for the builders interactive session."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from maistro_bootstrap.builders.session import BuilderSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model tier routing
#
# Each builder role maps to a capability tier.  LiteLLM resolves the alias
# to whichever provider the gateway is configured for, so "fast" might be
# claude-haiku-4-5 today and gemini-flash-2 tomorrow — the builders never
# care about the underlying provider.
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = (
    os.environ.get("MAISTRO_BUILDERS_MODEL")
    or os.environ.get("DEFAULT_MODEL")
    or "claude-sonnet-4-6"
)

# Builders picks the best model for each role; override any tier via env.
_MODEL_TIERS: dict[str, str] = {
    # Heavy reasoning: code generation, test writing, review
    "capable": os.environ.get("BUILDERS_MODEL_CAPABLE") or _DEFAULT_MODEL,
    # Fast/cheap: clarification, search, bookkeeping, setup
    "fast": (
        os.environ.get("BUILDERS_MODEL_FAST")
        or os.environ.get("BUILDERS_FAST_MODEL")
        or "claude-haiku-4-5"
    ),
}

# Worker → tier mapping.  Workers not listed default to "capable".
_WORKER_TIER: dict[str, str] = {
    "arbiter": "fast",  # clarification loop — quick back-and-forth
    "scout": "fast",  # search/lookup — cheap retrieval
    "quartermaster": "fast",  # env setup — deterministic, not creative
    "janitor": "fast",  # PR/issue cleanup — structured, low-complexity
    "frank": "capable",  # implementation — needs full reasoning
    "mason": "capable",  # test writing — needs to understand code deeply
    "auditor": "capable",  # review — needs full reasoning
    "archie": "capable",  # architecture — complex planning
}


def model_for_worker(worker: str) -> str:
    """Return the best model alias for a given worker name.

    Checks the benchmark cache first; falls back to _MODEL_TIERS defaults
    if the cache is missing or the gateway is unreachable.
    """
    tier = _WORKER_TIER.get(worker.lower(), "capable")
    # Try cached winner first (avoids network call on every session start)
    try:
        from maistro_bootstrap.builders.model_selector import load_cache

        cache = load_cache()
        if cache and cache.get(f"{tier}_model"):
            return str(cache[f"{tier}_model"])
    except Exception:
        pass
    return _MODEL_TIERS[tier]


@dataclass
class AgentLoopConfig:
    """Tunable parameters for the agent loop."""

    max_turns: int = 10
    max_tokens: int = 8192
    # None → resolved per-worker via model_for_worker(); set explicitly to override.
    model: str | None = None
    worker: str = "frank"
    system_prompt: str = (
        "You are a precise coding assistant working inside an isolated git worktree. "
        "Use the provided tools to read files, write changes, and run commands. "
        "Always confirm destructive actions before executing them. "
        "Never access paths outside the workspace root."
    )
    tool_definitions: list[dict[str, Any]] = field(default_factory=list)

    def resolved_model(self) -> str:
        return self.model or model_for_worker(self.worker)


def _make_sandbox_tools(session: BuilderSession) -> list[dict[str, Any]]:
    """Return Anthropic-format tool definitions that delegate to the sandbox.

    Structured tools (run_tests, run_lint, git_status, git_diff) map to fixed
    argv lists executed with shell=False — no LLM-controlled string reaches the
    shell.  run_command is retained for flexibility but is narrowed: the sandbox
    applies metachar rejection + shlex parsing + path-escape checks, and callers
    must set requires_human_approval=true for anything outside the common cases.
    """
    return [
        {
            "name": "read_file",
            "description": "Read a file from the sandbox workspace.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative file path"}},
                "required": ["path"],
            },
        },
        {
            "name": "edit_file",
            "description": (
                "PREFERRED for changing an existing file: replace one exact string. "
                "`old_string` must match the file byte-for-byte (including indentation) "
                "and appear EXACTLY ONCE — include enough surrounding lines to be unique. "
                "`new_string` replaces it. Use this instead of write_file for edits so you "
                "don't rewrite (or accidentally reformat) the rest of the file."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to replace; must be unique in the file.",
                    },
                    "new_string": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
        {
            "name": "write_file",
            "description": (
                "Write a whole file. Use only for NEW files or full rewrites; prefer "
                "edit_file for changes to an existing file."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        # --- structured safe tools (shell=False, fixed argv) ---
        {
            "name": "run_tests",
            "description": "Run pytest in the sandbox workspace. Prefer this over run_command for tests.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "Extra pytest args e.g. '-k my_test -q'. No shell metacharacters.",
                    }
                },
            },
        },
        {
            "name": "run_lint",
            "description": "Run ruff check on the sandbox workspace.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "git_status",
            "description": "Show git status of the sandbox workspace.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "git_diff",
            "description": "Show git diff of changes in the sandbox workspace.",
            "input_schema": {"type": "object", "properties": {}},
        },
        # --- free-form command (narrowed; validated by SandboxedShell) ---
        {
            "name": "run_command",
            "description": (
                "Run an arbitrary command in the sandbox. "
                "Shell metacharacters (;|&<>`$\\) are rejected. "
                "Use structured tools (run_tests, run_lint, git_status) when possible. "
                "Set requires_human_approval=true for any destructive or network operation."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "timeout": {"type": "integer", "default": 30},
                    "requires_human_approval": {
                        "type": "boolean",
                        "description": "Set true for destructive/network commands.",
                        "default": False,
                    },
                },
                "required": ["cmd"],
            },
        },
        {
            "name": "search",
            "description": "Search files in the workspace for a pattern.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "glob": {"type": "string", "default": "**/*.py"},
                },
                "required": ["pattern"],
            },
        },
    ]


def _dispatch_safe_tool(sandbox: Any, name: str, inputs: dict[str, Any]) -> str | None:
    """Handle structured tools that use fixed argv (shell=False). Returns None if unrecognised."""
    if name == "read_file":
        return str(sandbox.read_file(inputs["path"]))
    if name == "write_file":
        sandbox.write_file(inputs["path"], inputs["content"])
        return f"wrote {inputs['path']}"
    if name == "edit_file":
        return str(sandbox.edit_file(inputs["path"], inputs["old_string"], inputs["new_string"]))
    if name == "run_tests":
        argv = ["python", "-m", "pytest"]
        extra = inputs.get("args", "").strip()
        if extra:
            argv += extra.split()
        return str(sandbox.run_argv(argv))
    if name == "run_lint":
        return str(sandbox.run_argv(["ruff", "check", "."]))
    if name == "git_status":
        return str(sandbox.run_argv(["git", "status"]))
    if name == "git_diff":
        return str(sandbox.diff())
    if name == "search":
        return json.dumps(sandbox.search(inputs["pattern"], glob=inputs.get("glob", "**/*.py")))
    return None


def _dispatch_tool(session: BuilderSession, name: str, inputs: dict[str, Any]) -> str:
    sandbox = session.sandbox
    try:
        result = _dispatch_safe_tool(sandbox, name, inputs)
        if result is not None:
            return result
        if name == "run_command":
            if inputs.get("requires_human_approval"):
                logger.warning("run_command flagged for human approval — cmd=%r", inputs["cmd"])
                return (
                    f"[REQUIRES_HUMAN_APPROVAL] Command not executed automatically: {inputs['cmd']!r}. "
                    "Confirm in the TUI to proceed."
                )
            return sandbox.run_command(inputs["cmd"], timeout=inputs.get("timeout", 30))
    except Exception as exc:
        return f"[tool error] {exc}"
    return f"[unknown tool] {name}"


class TurnRunner:
    """Executes one agent turn: sends messages to the LLM, handles tool calls.

    If no LLM is set explicitly via set_llm(), a LiteLLMCallable is
    auto-constructed using config.resolved_model() — which picks the right
    model tier for the current worker (fast vs capable).
    """

    def __init__(self, session: BuilderSession, config: AgentLoopConfig) -> None:
        self._session = session
        self._config = config
        self._llm: Callable[..., dict[str, Any]] | None = None

    def set_llm(self, llm: Callable[..., dict[str, Any]]) -> None:
        self._llm = llm

    def _get_llm(self) -> Callable[..., dict[str, Any]]:
        if self._llm is None:
            from maistro_bootstrap.builders.responses_callable import LiteLLMCallable

            self._llm = LiteLLMCallable(model=self._config.resolved_model())
            logger.info(
                "auto-wired LiteLLM model=%s worker=%s",
                self._config.resolved_model(),
                self._config.worker,
            )
        return self._llm

    async def execute_turn(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        import asyncio
        import functools

        llm = self._get_llm()
        tools = _make_sandbox_tools(self._session)
        full_messages = list(messages)

        for _ in range(self._config.max_turns):
            # Run the sync HTTP call in a thread so it doesn't block the event loop.
            call = functools.partial(
                llm,
                full_messages,
                tools=tools,
                max_tokens=self._config.max_tokens,
            )
            result = await asyncio.to_thread(call)

            if result.get("stop_reason") != "tool_use":
                self._session.add_assistant(result.get("content", ""))
                return result

            # Tool use loop
            tool_results = []
            content = result.get("content", "")
            # content may be a list of blocks when tools fire
            blocks = content if isinstance(content, list) else []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_out = _dispatch_tool(self._session, block["name"], block.get("input", {}))
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": tool_out,
                        }
                    )
                    logger.debug("tool=%s result_len=%d", block["name"], len(tool_out))

            full_messages.append({"role": "assistant", "content": blocks})
            full_messages.append({"role": "user", "content": tool_results})

        return {
            "content": "(max turns reached)",
            "stop_reason": "max_turns",
            # The accumulated transcript: seed messages plus every tool_use/
            # tool_result exchange this budget consumed. "max_turns" is an
            # INTERNAL budget stop — the model was cut off mid-work, it did not
            # choose to finish. A caller that wants the work to continue must
            # resume from this transcript; quoting the sentinel back to the
            # model as its own words makes it believe it announced running out
            # of turns, so it apologises and stops instead of working.
            "messages": full_messages,
        }
