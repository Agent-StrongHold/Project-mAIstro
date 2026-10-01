"""Execute model-generated benchmark code inside MAIstro's Docker sandbox.

The proxy SWE-bench evaluator receives raw LLM output, so candidate code is
untrusted by definition. It must never execute directly on the evaluator host.
This module therefore delegates execution to ``maistro.tools.sandbox`` and
fails closed when the isolated runtime is unavailable.

The sandbox provides the controls the benchmark needs at this trust boundary:
network isolation, bounded memory/CPU/PIDs, a restricted temporary workspace
mount, environment sanitization, timeout handling, and container teardown.
``maistro-evolve`` intentionally does not add a package dependency on
``maistro-core`` because the dependency direction is otherwise reversed. The
import is runtime-only: MAIstro's integrated RSI/evolve runtime provides core;
a standalone evolve installation simply cannot execute this untrusted-code
benchmark and returns a failed check instead of weakening isolation.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

_DEFAULT_TIMEOUT = 10.0
_MAX_OUTPUT_CHARS = 500
_PASS_MARKER = "PASS"


def _build_check_script(
    code: str,
    function_name: str,
    cases: list[tuple[list[Any], Any]],
) -> str:
    """Candidate code followed by evaluator-only calls and comparisons.

    Case arguments/expected values come only from the maintainer-authored
    evaluator, never from model output. Expected values are evaluated in a
    separate namespace so candidate globals cannot accidentally rebind names
    used by values such as ``datetime``.
    """
    case_rows = ",\n".join(f"    ({args!r}, {repr(expected)!r})" for args, expected in cases)
    return (
        f"{code}\n\n"
        "import datetime as _maistro_datetime_module\n"
        f"_cases = [\n{case_rows}\n]\n"
        "for _args, _expected_expr in _cases:\n"
        f"    _result = {function_name}(*_args)\n"
        "    _expected = eval(_expected_expr, {'datetime': _maistro_datetime_module})\n"
        "    if _result != _expected:\n"
        "        print(f'FAIL: args={_args!r}, got {_result!r}, expected {_expected!r}')\n"
        "        raise SystemExit(1)\n"
        "print('PASS')\n"
    )


async def run_function_checks(
    code: str,
    function_name: str,
    cases: list[tuple[list[Any], Any]],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[bool, str]:
    """Run a batch of candidate assertions in one isolated Docker sandbox.

    There is deliberately no host-process fallback: if Docker/core sandbox
    support is unavailable, the check fails rather than executing generated
    Python with host filesystem/network access.
    """
    if not cases:
        return False, "no evaluator cases provided"

    script = _build_check_script(code, function_name, cases)

    try:
        from maistro.config.settings import SandboxSettings
        from maistro.tools.sandbox.docker import create_sandbox
    except ImportError as exc:
        return False, f"isolated sandbox unavailable: {exc}"[:_MAX_OUTPUT_CHARS]

    # ``ensure_workspace`` only permits MAIstro's dedicated temporary root (or
    # /repos). Build the evaluator directory under that root rather than using
    # an arbitrary tempfile path that the sandbox correctly refuses to mount.
    sandbox_root = Path(tempfile.gettempdir()) / "maistro-workspace" / "swebench-eval"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    sandbox_root.chmod(0o755)

    with tempfile.TemporaryDirectory(prefix="case-", dir=sandbox_root) as tmp_name:
        tmp = Path(tmp_name)

        # TemporaryDirectory deliberately creates directories as 0700. The
        # sandbox drops CAP_DAC_OVERRIDE, so container root cannot traverse a
        # host-owned 0700 bind mount. Make only the case directory traversable
        # and the evaluator script read-only: the container can execute it but
        # untrusted candidate code cannot modify the mounted evaluator.
        tmp.chmod(0o755)
        check_path = tmp / "check.py"
        check_path.write_text(script, encoding="utf-8")
        check_path.chmod(0o444)

        # Keep the container alive slightly longer than the per-command budget;
        # network isolation is forced on even if an operator's general sandbox
        # defaults are looser.
        settings = SandboxSettings(
            memory_limit="256m",
            cpu_count=1,
            timeout=max(15, math.ceil(timeout) + 5),
            network_disabled=True,
        )

        try:
            sandbox = await create_sandbox(str(tmp), settings=settings, env={})
            async with sandbox:
                exit_code, output = await sandbox.exec(
                    "python check.py",
                    timeout=max(1, math.ceil(timeout)),
                )
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError, OSError) as exc:
            return False, f"isolated sandbox unavailable: {exc}"[:_MAX_OUTPUT_CHARS]

    output = output.strip()
    if exit_code != 0:
        detail = output or f"exit code {exit_code}"
        return False, detail[:_MAX_OUTPUT_CHARS]
    if output == _PASS_MARKER:
        return True, "ok"
    return False, (output or "no PASS marker in output")[:_MAX_OUTPUT_CHARS]
