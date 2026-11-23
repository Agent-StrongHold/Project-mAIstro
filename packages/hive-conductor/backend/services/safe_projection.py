"""The single safe-projection policy for public failure disclosure (#2465).

One module owns what may cross a public boundary — the DAG run receipts,
the websocket/SSE projections, and the Design routes' exception responses —
so no transport can drift into its own dialect of redaction.

The policy, and the boundary it draws:

- **Failure kinds, never failure text.** Exception messages carry filesystem
  paths, internal hostnames and whole provider replies (CodeQL
  py/stack-trace-exposure). A public body may name the exception's class or a
  bounded, host-authored failure kind; the text stays in the server log and
  in the canonical Run/NodeRun/Attempt/Event records.
- **Nested fields obey the same rule.** A failed node's projected ``response``
  is the node's raw error text (`canonical_dag_runner._node_results` used to
  copy ``node_run.error`` there verbatim), so a receipt whose top-level error
  is sanitized still leaked through ``result["node_results"][*]["response"]``
  and ``result["error"]`` (#2465). The policy applies to the whole body.
- **Authorized task output stays visible.** A *successful* node's response is
  the user's own task output, not failure evidence; it crosses the boundary
  verbatim under this explicit presentation contract (pinned by tests).
- **Canonical truth is never redacted.** This module formats HTTP bodies; it
  never touches the persisted Run/NodeRun/Attempt/Event evidence. Authorized
  inspection (the #1877 canonical overlay on ``GET /v1/dag-runs/{id}`` and the
  maistro-server run inspection plane) keeps serving the full bounded evidence
  for forensics — bounded at write time by the canonical failure authority
  (`maistro.graph.durable_runs.sanitize_failure_message`), never here.
- **Host-authored structured kinds are preserved.** A canonical Run can fail
  with a *classified* failure whose message the host itself authored and
  bounded (cycle/step budget exhaustion, attempt deadline, unknown node,
  halt, plan mismatch, replay refusal). Those names and sentences are safe,
  actionable disclosure ("run exceeded max_cycles=1 ..."), so
  `public_failure_text` keeps them; everything else — any unclassified or
  physical-execution error text — is bounded to a fixed sentence. The
  host's own node-execution refusal (`HOST_POLICY_NODE_REFUSAL`, raised by
  the node tier resolver when host policy blocks a node) is the same class:
  authored by the host, names no node id, path, provider or diagnostic, and
  is the actionable disclosure the public receipt has carried since the M1
  e2e contract pinned it (pm-workflow.spec.ts step 06). It is matched by
  sentence, never by wrapper kind (`PermissionError`): a PermissionError
  raised at a filesystem or network boundary carries unbounded text and
  stays bounded.
- **Failures stay failures.** Nothing here rewrites a status: a failed Run is
  projected as failed, with its Run id, never as a successful execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "HOST_AUTHORED_RUN_ERROR_CODES",
    "HOST_POLICY_NODE_REFUSAL",
    "NODE_FAILURE_TEXT",
    "RUN_FAILURE_TEXT",
    "node_failure_text",
    "public_failure",
    "public_failure_text",
    "safe_dag_result",
]

#: What replaces a failed node's projected response text.
NODE_FAILURE_TEXT = "node failed; see server logs"

#: What replaces an unclassified run error's text.
RUN_FAILURE_TEXT = "run failed; see server logs"

#: Canonical Run failure codes whose message is authored by the host (not by
#: an exception that crossed a provider/filesystem boundary) and bounded at
#: write time by `durable_runs` — safe, actionable disclosure. The message of
#: any other code (`PhysicalExecutionError`, `NodeFailure`, ...) is exception
#: text and is bounded here.
HOST_AUTHORED_RUN_ERROR_CODES = frozenset(
    {
        "AttemptDeadlineExceeded",
        "CycleBudgetExhausted",
        "HaltRequested",
        "PlanPostStateMismatch",
        "ReplayRefused",
        "StepBudgetExhausted",
        "UnknownNode",
    }
)

#: The host's own node-execution refusal (`legacy_dag_node` raises it when the
#: resolved execution tier is "blocked"). Host-authored and bounded — it names
#: no node id, filesystem path, provider or diagnostic — so it is safe,
#: actionable disclosure and crosses the boundary verbatim. The canonical
#: executor wraps it as ``PermissionError: <sentence>``, and the projection
#: matches the *sentence*, never the wrapper kind: a ``PermissionError`` from
#: a filesystem or network boundary carries unbounded text and stays bounded.
HOST_POLICY_NODE_REFUSAL = "Execution blocked: host policy did not authorize this node"


def public_failure(exc: BaseException) -> str:
    """The failure text a transport may show: the exception kind, never its message.

    One structured remediation is preserved: when the failure is the no-gateway
    stub refusal, name ``ALLOW_STUB_LLM`` so an operator can act without reading
    server logs. That is an env-var name, not exception detail.
    """
    detail = str(exc)
    if "ALLOW_STUB_LLM" in detail:
        return (
            f"{type(exc).__name__}: LLM gateway unset; "
            "set ALLOW_STUB_LLM=true to opt into stubs; see server logs"
        )
    return f"{type(exc).__name__}: execution failed; see server logs"


def public_failure_text(text: str) -> str:
    """`public_failure` for a failure string already extracted from canonical truth.

    Used where the code holds the text but no exception object — the projected
    Run error inside a DAG result. The same one structured remediation is
    preserved, host-authored failure kinds pass through, and everything else
    is bounded to the fixed sentence.
    """
    if "ALLOW_STUB_LLM" in text:
        return _stub_refusal_remediation()
    if HOST_POLICY_NODE_REFUSAL in text:
        return HOST_POLICY_NODE_REFUSAL
    code, sep, _message = text.partition(": ")
    if sep and code in HOST_AUTHORED_RUN_ERROR_CODES:
        return text
    return RUN_FAILURE_TEXT


def node_failure_text(_raw: object) -> str:
    """The public ``response`` for a failed node (#2465): the kind, only.

    A failed node's raw error text never crosses — it carries provider
    replies, paths and diagnostics. The bounded evidence stays on the
    canonical NodeRun for authorized inspection, and the run-level
    ``result["error"]`` projection (which keeps host-authored budget and
    deadline kinds, plus the ``ALLOW_STUB_LLM`` remediation) remains the
    actionable half of the disclosure. Kept as a named function so the
    projection seam states the contract instead of inlining a constant.
    """
    return NODE_FAILURE_TEXT


def _stub_refusal_remediation() -> str:
    return "LLM gateway unset; set ALLOW_STUB_LLM=true to opt into stubs; see server logs"


def safe_dag_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Project one DAG result for a public body under the #2465 policy.

    Returns a copy: top-level ``error`` text bounded through
    `public_failure_text`, every failed node's ``response`` bounded through
    `node_failure_text`, successful node responses preserved verbatim, and
    every other key (status, run_id, cycles, annotations, ...) untouched.
    Idempotent: applying it to an already-projected result changes nothing,
    so a route may apply it defensively over an executor that applied it
    first.
    """
    projected = dict(result)
    error = projected.get("error")
    if error:
        projected["error"] = public_failure_text(str(error))
    node_results = projected.get("node_results")
    if isinstance(node_results, Mapping):
        projected["node_results"] = {
            node_id: (
                {
                    **node,
                    "response": (node_failure_text(node.get("response"))),
                }
                if isinstance(node, Mapping) and not node.get("success")
                else dict(node)
                if isinstance(node, Mapping)
                else node
            )
            for node_id, node in node_results.items()
        }
    return projected
