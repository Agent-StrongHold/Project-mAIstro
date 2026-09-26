from __future__ import annotations

from typing import Any

import pytest

import maistro_evolve.benchmarks.swebench as swebench_module
from maistro.sandbox import ExecResult, SandboxSelector
from maistro_evolve.benchmarks.datasets import SWEBENCH_SAMPLES
from maistro_evolve.benchmarks.swebench import (
    _extract_code,
    _function_name,
    run_swebench,
)

from .conftest import make_genome


class _StubExecBackend:
    """A vm-tier backend whose exec returns a canned result.

    Candidate code must never execute on the host, so the stub does not run
    the script either — it stands in for the sandbox boundary the way the
    canonical backends' own tests do. Real-container execution of this
    benchmark is covered by the sandbox conformance suite (#80).
    """

    tier = "vm"
    supports_scoped_egress = False

    def __init__(self, exit_code: int, output: str) -> None:
        self._result = ExecResult(exit_code=exit_code, stdout=output, stderr="", duration_ms=1)
        self.exec_count = 0

    async def spawn(self, *, config: Any) -> object:
        return object()

    async def exec(self, instance: Any, command: list[str], *, timeout_s: int = 120) -> ExecResult:
        self.exec_count += 1
        return self._result

    async def read_file(self, instance: Any, path: str) -> bytes:
        raise NotImplementedError

    async def write_file(self, instance: Any, path: str, content: bytes) -> None:
        pass

    async def destroy(self, instance: Any) -> None:
        pass


def _patch_sandbox(
    monkeypatch: pytest.MonkeyPatch, exit_code: int, output: str
) -> _StubExecBackend:
    """Route the benchmark through a selector that has a vm-tier backend."""
    from maistro.tools.sandbox import docker as sandbox_docker

    backend = _StubExecBackend(exit_code, output)
    selector = SandboxSelector()
    selector.register("vm", backend)
    monkeypatch.setattr(sandbox_docker, "build_selector", lambda: selector)
    return backend


# A single small, fast sample used for most run_swebench tests. It deliberately
# uses the real swe_01 identity so the production evaluator supplies its
# undisclosed cases instead of letting a synthetic fixture bypass the hidden-
# case contract introduced to prevent prompt-example overfitting.
_FAST_SAMPLE = {
    "id": "swe_01",
    "problem": "flatten_list only handles one level of nesting.",
    "buggy_code": (
        "def flatten_list(lst):\n"
        "    result = []\n"
        "    for item in lst:\n"
        "        if isinstance(item, list):\n"
        "            result.extend(item)\n"
        "        else:\n"
        "            result.append(item)\n"
        "    return result"
    ),
    "expected_keywords": ["recursive"],
    "test_input": "[[1, [2, 3]], 4]",
    "expected_output": "[1, 2, 3, 4]",
    "call_args": [[[1, [2, 3]], 4]],
    "expected_value": [1, 2, 3, 4],
}

_CORRECT_FIX = (
    "```python\n"
    "def flatten_list(lst):\n"
    "    result = []\n"
    "    for item in lst:\n"
    "        if isinstance(item, list):\n"
    "            result.extend(flatten_list(item))\n"
    "        else:\n"
    "            result.append(item)\n"
    "    return result\n"
    "```"
)


# ---------------------------------------------------------------------------
# _extract_code
# ---------------------------------------------------------------------------


class TestExtractCode:
    def test_fenced_python_block(self) -> None:
        response = "Here:\n```python\ndef f():\n    return 1\n```\nDone."
        assert _extract_code(response) == "def f():\n    return 1\n"

    def test_multiple_fenced_blocks_joined(self) -> None:
        response = "```python\na = 1\n```\nmore\n```python\nb = 2\n```"
        assert _extract_code(response) == "a = 1\n\nb = 2\n"

    def test_no_fence_falls_back_to_raw_response(self) -> None:
        response = "def f():\n    return 1"
        assert _extract_code(response) == response

    def test_fence_without_language_tag(self) -> None:
        response = "```\ndef f():\n    return 1\n```"
        assert _extract_code(response) == "def f():\n    return 1\n"


# ---------------------------------------------------------------------------
# _function_name
# ---------------------------------------------------------------------------


class TestFunctionName:
    def test_extracts_simple_function_name(self) -> None:
        assert _function_name("def flatten_list(lst):\n    pass") == "flatten_list"

    def test_extracts_name_after_import(self) -> None:
        code = "from datetime import datetime\ndef parse_date(date_str):\n    pass"
        assert _function_name(code) == "parse_date"

    def test_no_function_definition_raises(self) -> None:
        with pytest.raises(ValueError, match="could not find a function definition"):
            _function_name("x = 1")


# ---------------------------------------------------------------------------
# run_swebench
# ---------------------------------------------------------------------------


class TestRunSwebench:
    async def test_llm_call_none_raises(self) -> None:
        genome = make_genome()
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_swebench(genome, None)

    async def test_correct_fix_scores_full_marks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_sandbox(monkeypatch, exit_code=0, output="PASS\n")
        monkeypatch.setattr(swebench_module, "SWEBENCH_SAMPLES", [_FAST_SAMPLE])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return _CORRECT_FIX

        result = await run_swebench(genome, llm_call)
        assert result.benchmark == "proxy_swebench"
        assert result.samples_evaluated == 1
        assert result.score == 1.0
        assert result.cost_usd > 0.0
        assert result.metadata["fidelity"] == "proxy"
        assert result.metadata["check"] == "isolated_hidden_assertion_batch"
        assert result.metadata["total_samples"] == 1
        assert result.metadata["failures"] == []

    async def test_host_without_vm_tier_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No registered backend meets the unattended/untrusted floor → the
        candidate is refused, scored zero, and never executed on the host
        (ADR-093 decision 6; #18 converged this seam onto the canonical
        ladder, which refuses on container-only hosts)."""
        from maistro.tools.sandbox import docker as sandbox_docker

        monkeypatch.setattr(sandbox_docker, "build_selector", SandboxSelector)  # nothing registered
        monkeypatch.setattr(swebench_module, "SWEBENCH_SAMPLES", [_FAST_SAMPLE])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return _CORRECT_FIX

        result = await run_swebench(genome, llm_call)
        assert result.score == 0.0
        assert result.metadata["failures"][0]["detail"].startswith("isolated sandbox unavailable")

    async def test_unfixed_buggy_code_scores_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(swebench_module, "SWEBENCH_SAMPLES", [_FAST_SAMPLE])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            # Model just echoes the original, unfixed code back.
            return f"```python\n{_FAST_SAMPLE['buggy_code']}\n```"

        result = await run_swebench(genome, llm_call)
        assert result.samples_evaluated == 1
        assert result.score == 0.0
        assert len(result.metadata["failures"]) == 1
        assert result.metadata["failures"][0]["id"] == "swe_01"

    async def test_malformed_response_fails_via_sandboxed_syntax_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-code response isn't a harness exception — it's a genuine
        sandboxed execution failure (SyntaxError), same as any other fail.
        The stub returns what a real sandbox prints for a script that cannot
        parse; the pin is that such output flows into `failures` unmodified."""
        _patch_sandbox(
            monkeypatch,
            exit_code=1,
            output='  File "check.py", line 1\n    I refuse to write code.\nSyntaxError: invalid syntax\n',
        )
        monkeypatch.setattr(swebench_module, "SWEBENCH_SAMPLES", [_FAST_SAMPLE])
        genome = make_genome()

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return "I refuse to write code."

        result = await run_swebench(genome, llm_call)
        assert result.samples_evaluated == 1
        assert result.score == 0.0
        assert "SyntaxError" in result.metadata["failures"][0]["detail"]

    async def test_llm_call_exception_increments_evaluated_without_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(swebench_module, "SWEBENCH_SAMPLES", [_FAST_SAMPLE])
        genome = make_genome()

        async def raising_llm_call(messages: Any, **kwargs: Any) -> str:
            raise RuntimeError("network error")

        result = await run_swebench(genome, raising_llm_call)
        assert result.samples_evaluated == 1
        assert result.score == 0.0
        assert result.cost_usd == 0.0

    async def test_llm_call_timeout_increments_evaluated_without_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(swebench_module, "SWEBENCH_SAMPLES", [_FAST_SAMPLE])
        genome = make_genome()

        async def hanging_llm_call(messages: Any, **kwargs: Any) -> str:
            raise TimeoutError()

        result = await run_swebench(genome, hanging_llm_call)
        assert result.samples_evaluated == 1
        assert result.score == 0.0

    async def test_llm_call_receives_model_config_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(swebench_module, "SWEBENCH_SAMPLES", [_FAST_SAMPLE])
        genome = make_genome(temperature=0.42, max_tokens=777)
        seen: dict[str, Any] = {}

        async def llm_call(messages: Any, temperature: float = 0.2, max_tokens: int = 2048) -> str:
            seen["temperature"] = temperature
            seen["max_tokens"] = max_tokens
            return _CORRECT_FIX

        await run_swebench(genome, llm_call)
        assert seen == {"temperature": 0.42, "max_tokens": 777}

    async def test_real_dataset_has_call_args_and_expected_value_on_every_sample(self) -> None:
        """Every sample must carry the fields run_swebench actually uses —
        this is the annotation contract added for real execution."""
        assert len(SWEBENCH_SAMPLES) == 10
        for sample in SWEBENCH_SAMPLES:
            assert "call_args" in sample
            assert "expected_value" in sample
            assert isinstance(sample["call_args"], list)
