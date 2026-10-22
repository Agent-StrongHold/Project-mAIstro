"""Execute model-generated benchmark code inside MAIstro's Docker sandbox.

The proxy SWE-bench evaluator receives raw LLM output, so candidate code is
untrusted by definition. It must never execute directly on the evaluator host.
This module therefore delegates execution to ``maistro.tools.sandbox`` and
fails closed when the isolated runtime is unavailable.

Verdict integrity (M4-G / #852). A candidate must never be able to influence
the pass/fail decision through anything it controls — stdout, stderr, exit
status, or process lifetime. The historical design failed this: candidate code
was concatenated into the evaluator script itself, so ``print("PASS")`` plus
an early ``raise SystemExit(0)`` produced a passing verdict without any
assertion ever running. The current design enforces four invariants:

1. **Process separation.** Candidate code runs only inside a disposable
   per-case subprocess (``python -I runner.py <function> <base64-args>``).
   It can crash, hang, exit early, or print arbitrary text; none of that is
   trusted. The runner process only *observes* the candidate function's
   result and reports it as one JSON envelope line.
2. **Out-of-band verdict.** The verdict is computed on the HOST by comparing
   the canonicalized observed result against maintainer-authored expected
   values. A candidate-printed ``PASS`` marker is inert: nothing in the
   verdict path ever reads candidate stdout looking for a marker.
3. **Hidden values never enter the sandbox.** Expected values stay on the
   host; only the per-case arguments — which the candidate must see to
   compute on — cross the boundary. A candidate cannot read the rubric out
   of the workspace and fake a passing result.
4. **Fail-closed observation.** A case passes only when the subprocess exits
   0 *and* emits a parseable ``{"ok": true, "result": ...}`` envelope *and*
   the canonicalized result equals the canonicalized expected value. Timeouts,
   non-zero exits, malformed output, and unserializable results all fail.

Canonicalization is strict and type-aware (``True`` is not ``1``, ``"1"`` is
not ``1.0``), so formatter-level spoofs do not compare equal to real results.

``maistro-evolve`` intentionally does not add a package dependency on
``maistro-core`` because the dependency direction is otherwise reversed. The
import is runtime-only: MAIstro's integrated RSI/evolve runtime provides core;
a standalone evolve installation simply cannot execute this untrusted-code
benchmark and returns a failed check instead of weakening isolation.
"""

from __future__ import annotations

import base64
import json
import math
import tempfile
from pathlib import Path
from typing import Any

_DEFAULT_TIMEOUT = 10.0
_MAX_OUTPUT_CHARS = 500
_SOLUTION_FILENAME = "solution.py"
_RUNNER_FILENAME = "runner.py"
_CANDIDATE_MODULE_NAME = "candidate_solution"

# A valid envelope is a JSON object carrying an ``ok`` observation flag (with
# ``result`` on success or ``error`` on failure). Candidate stdout/stderr is
# untrusted noise: any line that does not parse into such an object is
# ignored, and a parseable envelope is only ever compared against hidden
# expected values the candidate cannot know — so printing "PASS" (or a fake
# envelope) can never satisfy a case.
_ENVELOPE_KEY = "ok"


def _runner_source() -> str:
    """Source of the evaluator-owned per-case observer script.

    Kept as a function so tests can materialize the exact production script
    and execute it against hostile candidate inputs without Docker.
    """
    return '''"""Per-case result observer (evaluator-owned; not candidate code).

Runs one case against the candidate solution and prints a single JSON
envelope. This process is deliberately disposable: candidate code can crash,
exit, or spoof stdout here without affecting the pass/fail decision, which
is made on the host by comparing the observed result against hidden
expected values that are never present inside the sandbox.
"""

import base64
import importlib.util
import json
import sys

SOLUTION_PATH = "__SOLUTION_FILENAME__"


def _canonical(value):
    if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return {"__isoformat__": isoformat()}
    return {"__unserializable__": type(value).__name__}


def _load_function(function_name):
    spec = importlib.util.spec_from_file_location("__MODULE_NAME__", SOLUTION_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load candidate module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    function = getattr(module, function_name, None)
    if not callable(function):
        raise AttributeError(function_name + " is not callable after loading candidate code")
    return function


def main():
    if len(sys.argv) != 3:
        json.dump({"ok": False, "error": "ValueError"}, sys.stdout)
        return 2
    try:
        args = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
    except Exception:
        json.dump({"ok": False, "error": "ValueError"}, sys.stdout)
        return 2
    try:
        function = _load_function(sys.argv[1])
    except BaseException as exc:  # candidate code may raise anything at import
        json.dump({"ok": False, "error": type(exc).__name__}, sys.stdout)
        return 0
    try:
        result = function(*args)
    except BaseException as exc:
        json.dump({"ok": False, "error": type(exc).__name__}, sys.stdout)
        return 0
    json.dump({"ok": True, "result": _canonical(result)}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''.replace("__SOLUTION_FILENAME__", _SOLUTION_FILENAME).replace(
        "__MODULE_NAME__", _CANDIDATE_MODULE_NAME
    )


def _canonical_host(value: Any) -> Any:
    """Host-side twin of the runner's canonicalizer (type-aware, JSON-safe)."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical_host(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_host(item) for key, item in value.items()}
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return {"__isoformat__": isoformat()}
    return {"__unserializable__": type(value).__name__}


def _canonical_json(value: Any) -> str:
    """Strict, type-aware comparison form (True != 1, "1" != 1.0)."""
    return json.dumps(_canonical_host(value), sort_keys=True, separators=(",", ":"))


def _parse_result_envelope(output: str) -> dict[str, Any] | None:
    """Return the last parseable ``{"ok": ..., "result": ...}`` envelope line."""
    envelope: dict[str, Any] | None = None
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed: Any = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict) and _ENVELOPE_KEY in parsed:
            envelope = parsed
    return envelope


def _case_command(function_name: str, args: list[Any]) -> str:
    encoded = base64.b64encode(json.dumps(args).encode("utf-8")).decode("ascii")
    return f"python -I {_RUNNER_FILENAME} {function_name} {encoded}"


def _grade_case(
    exit_code: int,
    output: str,
    expected: Any,
    index: int,
    total: int,
) -> tuple[bool, str]:
    """Host-side, out-of-band verdict for one case.

    Everything here is computed from (a) the sandbox exit status and (b) the
    structured result envelope, compared against host-owned expected values.
    No candidate-controlled marker ("PASS" or otherwise) participates, and no
    expected value ever appears in the returned detail.
    """
    label = f"case {index}/{total}"
    if exit_code != 0:
        return False, f"{label}: candidate process failed (exit {exit_code})"[:_MAX_OUTPUT_CHARS]

    envelope = _parse_result_envelope(output)
    if envelope is None:
        return False, f"{label}: no parseable result envelope"[:_MAX_OUTPUT_CHARS]

    if envelope.get("ok") is not True:
        error = envelope.get("error")
        error_name = error if isinstance(error, str) else "UnknownError"
        return False, f"{label}: candidate error: {error_name}"[:_MAX_OUTPUT_CHARS]

    observed = envelope.get("result")
    if _canonical_json(observed) != _canonical_json(expected):
        return False, f"{label}: result mismatch"[:_MAX_OUTPUT_CHARS]

    return True, "ok"


async def run_function_checks(
    code: str,
    function_name: str,
    cases: list[tuple[list[Any], Any]],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[bool, str]:
    """Grade candidate code against evaluator-only cases, out-of-band.

    There is deliberately no host-process fallback: if Docker/core sandbox
    support is unavailable, the check fails rather than executing generated
    Python with host filesystem/network access.

    Returns ``(passed, detail)``. ``detail`` is safe for reflection metadata:
    expected values never enter the sandbox, so they can never leak into it.
    """
    if not cases:
        return False, "no evaluator cases provided"

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
        # host-owned 0700 bind mount. Make the case directory traversable and
        # both files read-only: the container can execute them, but untrusted
        # candidate code cannot modify the evaluator or its own solution file.
        tmp.chmod(0o755)
        solution_path = tmp / _SOLUTION_FILENAME
        solution_path.write_text(code, encoding="utf-8")
        solution_path.chmod(0o444)
        runner_path = tmp / _RUNNER_FILENAME
        runner_path.write_text(_runner_source(), encoding="utf-8")
        runner_path.chmod(0o444)

        # Keep the container alive slightly longer than the sum of per-case
        # budgets; network isolation is forced on even if an operator's general
        # sandbox defaults are looser.
        settings = SandboxSettings(
            memory_limit="256m",
            cpu_count=1,
            timeout=max(15, math.ceil(timeout) * len(cases) + 5),
            network_disabled=True,
        )

        try:
            sandbox = await create_sandbox(str(tmp), settings=settings, env={})
            async with sandbox:
                for index, (args, expected) in enumerate(cases, start=1):
                    exit_code, output = await sandbox.exec(
                        _case_command(function_name, args),
                        timeout=max(1, math.ceil(timeout)),
                    )
                    passed, detail = _grade_case(exit_code, output, expected, index, len(cases))
                    if not passed:
                        return False, detail
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError, OSError) as exc:
            return False, f"isolated sandbox unavailable: {exc}"[:_MAX_OUTPUT_CHARS]

    return True, "ok"
