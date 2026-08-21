from __future__ import annotations

from maistro.security.guardrail import (
    GuardrailAction,
    GuardrailResult,
    GuardrailThresholds,
    LoopPattern,
    ToolGuardrail,
)


def _call(
    guardrail: ToolGuardrail,
    tool: str,
    args: dict | None = None,
    result: object = None,
    error: str | None = None,
) -> GuardrailResult:
    return guardrail.record(tool, args or {}, result=result, error=error)


class TestGuardrailThresholds:
    def test_defaults(self):
        t = GuardrailThresholds()
        assert t.warn_after == 2
        assert t.block_after == 4
        assert t.same_tool_failure_warn == 3
        assert t.same_tool_failure_block == 5
        assert t.idempotent_warn == 2
        assert t.idempotent_block == 3


class TestToolGuardrailExactRepeat:
    def test_first_call_allowed(self):
        g = ToolGuardrail()
        r = _call(g, "read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.ALLOW

    def test_warn_on_repeat(self):
        g = ToolGuardrail()
        _call(g, "read_file", {"path": "/tmp/x"})
        _call(g, "read_file", {"path": "/tmp/x"})
        r = _call(g, "read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.WARN
        assert r.pattern == LoopPattern.EXACT_REPEAT
        assert r.repeat_count == 3

    def test_block_on_excessive_repeat(self):
        g = ToolGuardrail()
        for _ in range(4):
            _call(g, "read_file", {"path": "/tmp/x"})
        r = _call(g, "read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.BLOCK
        assert r.pattern == LoopPattern.EXACT_REPEAT

    def test_different_args_not_counted(self):
        g = ToolGuardrail()
        _call(g, "read_file", {"path": "/tmp/a"})
        _call(g, "read_file", {"path": "/tmp/b"})
        r = _call(g, "read_file", {"path": "/tmp/c"})
        assert r.action == GuardrailAction.ALLOW

    def test_different_tools_not_counted(self):
        g = ToolGuardrail()
        _call(g, "read_file", {"path": "/tmp/x"})
        _call(g, "write_file", {"path": "/tmp/x"})
        r = _call(g, "list_dir", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.ALLOW

    def test_custom_thresholds(self):
        g = ToolGuardrail(GuardrailThresholds(warn_after=1, block_after=2))
        _call(g, "read_file", {"path": "/tmp/x"})
        r = _call(g, "read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.WARN
        r = _call(g, "read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.BLOCK


class TestToolGuardrailSameToolFailures:
    def test_warn_on_repeated_failures(self):
        g = ToolGuardrail(GuardrailThresholds(same_tool_failure_warn=2, same_tool_failure_block=4))
        _call(g, "exec", {"cmd": "ls"}, error="permission denied")
        _call(g, "exec", {"cmd": "pwd"}, error="permission denied")
        r = _call(g, "exec", {"cmd": "whoami"}, error="permission denied")
        assert r.action == GuardrailAction.WARN
        assert r.pattern == LoopPattern.SAME_TOOL_FAILURES

    def test_block_on_excessive_failures(self):
        g = ToolGuardrail(GuardrailThresholds(same_tool_failure_warn=1, same_tool_failure_block=3))
        for i in range(3):
            _call(g, "exec", {"cmd": f"cmd{i}"}, error="fail")
        r = _call(g, "exec", {"cmd": "another"}, error="fail")
        assert r.action == GuardrailAction.BLOCK
        assert r.pattern == LoopPattern.SAME_TOOL_FAILURES

    def test_success_does_not_trigger_failure_pattern(self):
        g = ToolGuardrail()
        _call(g, "exec", {"cmd": "ls"}, result={"exit_code": 0})
        r = _call(g, "exec", {"cmd": "pwd"}, result={"exit_code": 0})
        assert r.action == GuardrailAction.ALLOW


class TestToolGuardrailIdempotent:
    def test_warn_on_same_result(self):
        g = ToolGuardrail(GuardrailThresholds(idempotent_warn=1, idempotent_block=3))
        _call(g, "read_file", {"path": "/tmp/x"}, result="same content")
        r = _call(g, "read_file", {"path": "/tmp/x"}, result="same content")
        assert r.action == GuardrailAction.WARN
        assert r.pattern == LoopPattern.IDEMPOTENT_NO_PROGRESS

    def test_different_result_not_flagged(self):
        g = ToolGuardrail()
        _call(g, "read_file", {"path": "/tmp/x"}, result="content v1")
        r = _call(g, "read_file", {"path": "/tmp/x"}, result="content v2")
        assert r.action == GuardrailAction.ALLOW

    def test_block_on_idempotent_loop(self):
        g = ToolGuardrail(
            GuardrailThresholds(
                warn_after=10,
                block_after=20,
                idempotent_warn=1,
                idempotent_block=2,
            )
        )
        _call(g, "read_file", {"path": "/tmp/x"}, result="same")
        _call(g, "read_file", {"path": "/tmp/x"}, result="same")
        r = _call(g, "read_file", {"path": "/tmp/x"}, result="same")
        assert r.action == GuardrailAction.BLOCK
        assert r.pattern == LoopPattern.IDEMPOTENT_NO_PROGRESS


class TestToolGuardrailCheck:
    def test_check_before_call(self):
        g = ToolGuardrail()
        for _ in range(4):
            _call(g, "read_file", {"path": "/tmp/x"})
        r = g.check("read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.BLOCK

    def test_check_allows_new_call(self):
        g = ToolGuardrail()
        r = g.check("read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.ALLOW


class TestToolGuardrailReset:
    def test_reset_clears_history(self):
        g = ToolGuardrail()
        for _ in range(5):
            _call(g, "read_file", {"path": "/tmp/x"})
        assert len(g.history) == 5
        g.reset()
        assert len(g.history) == 0
        r = _call(g, "read_file", {"path": "/tmp/x"})
        assert r.action == GuardrailAction.ALLOW


class TestToolGuardrailHistory:
    def test_history_trims(self):
        g = ToolGuardrail(max_history=10)
        for i in range(20):
            _call(g, "read_file", {"path": f"/tmp/{i}"})
        assert len(g.history) == 10

    def test_history_preserves_recent(self):
        g = ToolGuardrail(max_history=5)
        for i in range(10):
            _call(g, "read_file", {"path": f"/tmp/{i}"})
        assert g.history[-1].args_hash != g.history[0].args_hash


class TestToolGuardrailHashConsistency:
    def test_same_args_same_hash(self):
        g = ToolGuardrail()
        _call(g, "test", {"a": 1, "b": 2})
        _call(g, "test", {"b": 2, "a": 1})
        assert g.history[0].args_hash == g.history[1].args_hash

    def test_different_args_different_hash(self):
        g = ToolGuardrail()
        _call(g, "test", {"a": 1})
        _call(g, "test", {"a": 2})
        assert g.history[0].args_hash != g.history[1].args_hash


class TestToolGuardrailPriority:
    def test_exact_repeat_takes_priority_over_same_tool(self):
        g = ToolGuardrail(
            GuardrailThresholds(
                warn_after=2,
                block_after=3,
                same_tool_failure_warn=1,
                same_tool_failure_block=5,
            )
        )
        _call(g, "exec", {"cmd": "ls"}, error="fail")
        _call(g, "exec", {"cmd": "ls"}, error="fail")
        r = _call(g, "exec", {"cmd": "ls"}, error="fail")
        assert r.pattern == LoopPattern.EXACT_REPEAT
