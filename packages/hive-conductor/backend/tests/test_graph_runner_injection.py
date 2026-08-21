"""Security: subprocess DAG nodes must not template untrusted strings into source.

services/graph_runner.py:run_node_subprocess() built a Python script via
f-string interpolation of node['prompt'], task_desc and parent context,
escaping only the double-quote character. A prompt containing triple-quotes,
backslashes or newlines breaks out of the string literal and can inject
arbitrary Python into the subprocess (RCE on the node host).

The fix passes these values into the subprocess as data (env vars), never
templated into the source. These tests pin that:

1. The script source is static and contains NO fragment of the attacker payload.
2. The payload reaches the node intact (via env), so behaviour is preserved.
3. The same hardening applies to the Hyperlight wrapper (base64, not templating).
"""

from __future__ import annotations

import ast
import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


_PAYLOAD_MARKER = "PWNED_INJECTION_MARKER"
# A prompt that breaks quote-only escaping: triple-quotes, backslashes, newlines.
_MALICIOUS_PROMPT = (
    'normal text """\n'
    "import os; os.system('echo " + _PAYLOAD_MARKER + "')\n"
    "back\\slash and \"quote\" and '''triple''' end"
)


class _StubExecutor:
    """Captures the script + env handed to execute_node."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_node(
        self,
        code: str,
        env: dict[str, str] | None = None,
        timeout_s: int = 120,
        allow_network: bool = False,
        memory_mb: int = 256,
        mode: str = "autonomous",
    ) -> dict[str, Any]:
        self.calls.append({"code": code, "env": env or {}})
        return {"success": True, "output": "ok", "isolation": "stub"}


@pytest.fixture()
def stub_executor(monkeypatch: pytest.MonkeyPatch) -> _StubExecutor:
    import services.hyperlight_executor as hx

    stub = _StubExecutor()
    monkeypatch.setattr(hx, "get_executor", lambda: stub)
    return stub


def test_node_script_is_static_with_no_untrusted_interpolation() -> None:
    """The subprocess script template is constant and valid Python — it does
    not contain any per-node prompt/task/context interpolation point."""
    from services.graph_runner import _NODE_SCRIPT

    ast.parse(_NODE_SCRIPT)
    # Untrusted values are read from env at runtime, so the static template must
    # reference them via os.environ, not splice them in.
    assert 'os.environ.get("DAG_NODE_SYSTEM"' in _NODE_SCRIPT
    assert 'os.environ.get("DAG_NODE_TASK"' in _NODE_SCRIPT
    assert 'os.environ.get("DAG_NODE_CONTEXT"' in _NODE_SCRIPT


def test_malicious_prompt_not_templated_into_subprocess_source(
    stub_executor: _StubExecutor,
) -> None:
    """A node prompt with triple-quotes/backslashes/newlines must not appear in
    the generated subprocess source, and the script stays valid Python."""
    from services.graph_runner import _run_node_subprocess

    node = {"id": "n1", "role": "worker", "prompt": _MALICIOUS_PROMPT}
    out = _run_node_subprocess(
        node,
        task_desc='task with """ and \\ and newlines\n!!!',
        context='ctx """ \\ \n more',
        base_env={"LITELLM_API_BASE": "http://x"},
    )
    assert out["success"] is True
    assert len(stub_executor.calls) == 1

    code = stub_executor.calls[0]["code"]
    # The payload must NOT be embedded in the script source at all.
    assert _PAYLOAD_MARKER not in code
    assert "os.system" not in code
    assert _MALICIOUS_PROMPT not in code
    # The generated source must be syntactically valid Python (no break-out).
    ast.parse(code)


def test_malicious_prompt_reaches_node_intact_as_data(
    stub_executor: _StubExecutor,
) -> None:
    """The prompt/task/context are passed as env data, preserved byte-for-byte
    so node behaviour is unchanged by the security fix."""
    from services.graph_runner import _run_node_subprocess

    _run_node_subprocess(
        {"id": "n1", "role": "worker", "prompt": _MALICIOUS_PROMPT},
        task_desc="my-task",
        context="my-context",
        base_env={},
    )
    env = stub_executor.calls[0]["env"]
    assert env["DAG_NODE_SYSTEM"] == _MALICIOUS_PROMPT
    assert env["DAG_NODE_TASK"] == "my-task"
    assert env["DAG_NODE_CONTEXT"] == "my-context"


class _JsonEnvelopeExecutor:
    """Like _StubExecutor, but returns the JSON-envelope shape _NODE_SCRIPT
    now emits (content + usage) instead of a plain string."""

    def __init__(self, usage: dict[str, Any] | None) -> None:
        self._usage = usage

    async def execute_node(self, code: str, **kw: Any) -> dict[str, Any]:
        import json

        return {
            "success": True,
            "output": json.dumps({"content": "the answer", "usage": self._usage}),
            "isolation": "stub",
        }


def test_run_node_subprocess_extracts_usage_from_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.hyperlight_executor as hx
    from services.graph_runner import _run_node_subprocess

    monkeypatch.setattr(
        hx,
        "get_executor",
        lambda: _JsonEnvelopeExecutor({"prompt_tokens": 5, "completion_tokens": 7}),
    )

    out = _run_node_subprocess(
        {"id": "n1", "role": "worker"}, task_desc="x", context="", base_env={}
    )

    assert out["success"] is True
    assert out["response"] == "the answer"
    assert out["usage"] == {"prompt_tokens": 5, "completion_tokens": 7}


def test_run_node_subprocess_falls_back_gracefully_on_malformed_envelope(
    stub_executor: _StubExecutor,
) -> None:
    """stub_executor returns a plain "ok" string, not JSON -- must degrade to
    treating it as the content with no usage, not crash."""
    from services.graph_runner import _run_node_subprocess

    out = _run_node_subprocess(
        {"id": "n1", "role": "worker"}, task_desc="x", context="", base_env={}
    )

    assert out["success"] is True
    assert out["response"] == "ok"
    assert out.get("usage") is None


def test_invoke_subprocess_usage_hooks_calls_on_response_with_usage() -> None:
    from services.graph_runner import _invoke_subprocess_usage_hooks

    captured: list[tuple[dict[str, Any], Any]] = []

    def on_response(data: dict[str, Any], response: Any) -> None:
        captured.append((data, response))

    results = {
        "n1": {"success": True, "response": "a", "usage": {"prompt_tokens": 1}},
        "n2": {"success": True, "response": "b"},  # no usage key at all
    }
    _invoke_subprocess_usage_hooks(["n1", "n2"], results, on_response)

    assert len(captured) == 1
    data, response = captured[0]
    assert data == {"usage": {"prompt_tokens": 1}}
    assert response.json() == {"usage": {"prompt_tokens": 1}}


def test_invoke_subprocess_usage_hooks_no_op_without_on_response() -> None:
    from services.graph_runner import _invoke_subprocess_usage_hooks

    # Must not raise -- on_response=None is the default, common case.
    _invoke_subprocess_usage_hooks(["n1"], {"n1": {"usage": {"prompt_tokens": 1}}}, None)


def test_invoke_subprocess_usage_hooks_swallows_a_failing_hook() -> None:
    from services.graph_runner import _invoke_subprocess_usage_hooks

    def broken_hook(data: dict[str, Any], response: Any) -> None:
        raise RuntimeError("recording hook blew up")

    # Must not raise -- instrumentation on an already-successful node must
    # never turn into a failure the caller has to handle.
    _invoke_subprocess_usage_hooks(["n1"], {"n1": {"usage": {"prompt_tokens": 1}}}, broken_hook)


def test_hyperlight_wrapper_uses_base64_not_string_templating() -> None:
    """The Hyperlight wrapper must base64-encode untrusted code, not splice it
    into a triple-quoted literal (which broke on triple-quotes/backslashes)."""
    import asyncio

    from services.hyperlight_executor import SandboxExecutor

    malicious_code = (
        "print('a')\n''' + __import__('os').system('echo " + _PAYLOAD_MARKER + "') + '''"
    )

    captured: dict[str, str] = {}

    async def _fake_subprocess(self: Any, script: str, env: Any, timeout_s: int) -> dict[str, Any]:
        captured["script"] = script
        return {"output": "ok", "error": "", "success": True}

    ex = SandboxExecutor()
    ex._backend = "hyperlight"  # force the hyperlight wrapper path
    ex._subprocess = _fake_subprocess.__get__(ex, SandboxExecutor)  # type: ignore[attr-defined]

    asyncio.run(ex.execute_node(malicious_code, allow_network=False))

    wrapper = captured["script"]
    # Wrapper is valid Python and does not contain the raw payload.
    ast.parse(wrapper)
    assert _PAYLOAD_MARKER not in wrapper
    assert "os.system" not in wrapper
    assert malicious_code not in wrapper
