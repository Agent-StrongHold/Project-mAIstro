from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class LoopPattern(StrEnum):
    EXACT_REPEAT = "exact_repeat"
    SAME_TOOL_FAILURES = "same_tool_failures"
    IDEMPOTENT_NO_PROGRESS = "idempotent_no_progress"


class GuardrailAction(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class GuardrailResult:
    action: GuardrailAction = GuardrailAction.ALLOW
    pattern: LoopPattern | None = None
    repeat_count: int = 0
    message: str = ""


class ToolCallRecord(BaseModel):
    tool_name: str
    args_hash: str
    result_hash: str = ""
    error: str = ""
    timestamp: float = 0.0


class GuardrailThresholds(BaseModel):
    warn_after: int = 2
    block_after: int = 4
    same_tool_failure_warn: int = 3
    same_tool_failure_block: int = 5
    idempotent_warn: int = 2
    idempotent_block: int = 3


def _canonical_args(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, default=str)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class ToolGuardrail:
    def __init__(
        self,
        thresholds: GuardrailThresholds | None = None,
        max_history: int = 200,
    ) -> None:
        self._thresholds = thresholds or GuardrailThresholds()
        self._history: list[ToolCallRecord] = []
        self._max_history = max_history

    @property
    def history(self) -> list[ToolCallRecord]:
        return list(self._history)

    @property
    def thresholds(self) -> GuardrailThresholds:
        return self._thresholds

    def _trim(self) -> None:
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

    def record(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any | None = None,
        error: str | None = None,
    ) -> GuardrailResult:
        args_hash = _hash(_canonical_args(args))
        result_str = json.dumps(result, sort_keys=True, default=str) if result is not None else ""
        result_hash = _hash(result_str) if result_str else ""

        record = ToolCallRecord(
            tool_name=tool_name,
            args_hash=args_hash,
            result_hash=result_hash,
            error=error or "",
            timestamp=time.monotonic(),
        )
        self._history.append(record)
        self._trim()

        return self._evaluate(record)

    def check(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> GuardrailResult:
        args_hash = _hash(_canonical_args(args))
        exact_matches = [
            r for r in self._history if r.tool_name == tool_name and r.args_hash == args_hash
        ]
        if len(exact_matches) >= self._thresholds.block_after:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                pattern=LoopPattern.EXACT_REPEAT,
                repeat_count=len(exact_matches),
                message=f"Tool '{tool_name}' called with identical args {len(exact_matches)} times",
            )
        if len(exact_matches) >= self._thresholds.warn_after:
            return GuardrailResult(
                action=GuardrailAction.WARN,
                pattern=LoopPattern.EXACT_REPEAT,
                repeat_count=len(exact_matches),
                message=f"Tool '{tool_name}' repeating with identical args ({len(exact_matches)} times)",
            )
        return GuardrailResult(action=GuardrailAction.ALLOW)

    def _check_exact_repeat(self, current: ToolCallRecord) -> GuardrailResult | None:
        exact = [
            r
            for r in self._history[:-1]
            if r.tool_name == current.tool_name and r.args_hash == current.args_hash
        ]
        if len(exact) >= self._thresholds.block_after:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                pattern=LoopPattern.EXACT_REPEAT,
                repeat_count=len(exact) + 1,
                message=f"Exact repeat: '{current.tool_name}' with same args {len(exact) + 1} times",
            )
        if len(exact) >= self._thresholds.warn_after:
            return GuardrailResult(
                action=GuardrailAction.WARN,
                pattern=LoopPattern.EXACT_REPEAT,
                repeat_count=len(exact) + 1,
                message=f"Exact repeat warning: '{current.tool_name}' ({len(exact) + 1} times)",
            )
        return None

    def _check_same_tool_failures(self, current: ToolCallRecord) -> GuardrailResult | None:
        if not current.error:
            return None
        same_tool_errors = [
            r for r in self._history[:-1] if r.tool_name == current.tool_name and r.error
        ]
        if len(same_tool_errors) >= self._thresholds.same_tool_failure_block:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                pattern=LoopPattern.SAME_TOOL_FAILURES,
                repeat_count=len(same_tool_errors) + 1,
                message=f"Same-tool failures: '{current.tool_name}' failed {len(same_tool_errors) + 1} times",
            )
        if len(same_tool_errors) >= self._thresholds.same_tool_failure_warn:
            return GuardrailResult(
                action=GuardrailAction.WARN,
                pattern=LoopPattern.SAME_TOOL_FAILURES,
                repeat_count=len(same_tool_errors) + 1,
                message=f"Same-tool failure warning: '{current.tool_name}' ({len(same_tool_errors) + 1} failures)",
            )
        return None

    def _check_idempotent_no_progress(self, current: ToolCallRecord) -> GuardrailResult | None:
        if not (current.result_hash and not current.error):
            return None
        idempotent = [
            r
            for r in self._history[:-1]
            if r.tool_name == current.tool_name
            and r.args_hash == current.args_hash
            and r.result_hash == current.result_hash
            and not r.error
        ]
        if len(idempotent) >= self._thresholds.idempotent_block:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                pattern=LoopPattern.IDEMPOTENT_NO_PROGRESS,
                repeat_count=len(idempotent) + 1,
                message=f"Idempotent no-progress: '{current.tool_name}' returning same result {len(idempotent) + 1} times",
            )
        if len(idempotent) >= self._thresholds.idempotent_warn:
            return GuardrailResult(
                action=GuardrailAction.WARN,
                pattern=LoopPattern.IDEMPOTENT_NO_PROGRESS,
                repeat_count=len(idempotent) + 1,
                message=f"Idempotent warning: '{current.tool_name}' same result ({len(idempotent) + 1} times)",
            )
        return None

    def _evaluate(self, current: ToolCallRecord) -> GuardrailResult:
        checks = (
            self._check_exact_repeat,
            self._check_same_tool_failures,
            self._check_idempotent_no_progress,
        )
        for check in checks:
            result = check(current)
            if result is not None:
                return result
        return GuardrailResult(action=GuardrailAction.ALLOW)

    def reset(self) -> None:
        self._history.clear()
