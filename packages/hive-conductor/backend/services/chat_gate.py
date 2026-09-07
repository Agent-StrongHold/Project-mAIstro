"""The Warden boundary for Conductor's chat and voice surfaces (#315).

Every external chat or voice message used to reach the model — and, on the
tool-capable internal loop, `_execute_tool` — without crossing the prompt
injection gate the webhook, harness, and HITL paths already use. This module
is that gate, and it deliberately owns no detector of its own: it wraps
`routes.agents.scan_config`, the same Warden walk the HITL door answers
through, so "what counts as hostile" cannot drift between surfaces.

Explicit failure policy — the point of the module. A gate must never
silently bypass, so every way a scan can end without a verdict is a refusal
with its own reason:

- `flagged`            the Warden found something; the turn is refused.
- `scanner_timeout`    the scan exceeded `SCAN_TIMEOUT_SECONDS`; refused.
- `scanner_error`      the scanner raised, or returned a shape that is not a
                       verdict; refused. Malformed scanner output is a
                       failure, not a pass.
- `budget_exceeded`    the payload is larger or deeper than the scanner walks
                       (re-exported from `routes.agents`); refused.

Tool policy — authorization independent of model judgment. Model-authored
tool selection crosses this boundary too, and the effect classes below are
what the backend requires before a tool with that effect may run:

- `destroy`/`mutate`  privileged effects: refused unless the caller presents
                      an approval the model cannot mint (`approved=True` on
                      the dispatcher, with the approval recorded in audit).
- `network`           a principal is required: with no authenticated user
                      there is no authorization at all, so the call refuses.
- `read`              local, user-scoped reads; audited, allowed.

External chat and voice surfaces remain conversational-only under the M0
containment (#483/#484), so no model-driven tool call can originate there;
this policy is the enforcement point that governs the internal loop and any
future re-enablement.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from routes.agents import ScanBudgetExceeded, scan_config
from routes.audit import log_audit

#: Bumped whenever the policy below changes shape — new refusal reason,
#: changed timeout, changed tool classification — so every recorded decision
#: names the rules it was judged by.
POLICY_VERSION = "chat-gate/1"

#: How long one scan may run before the turn fails closed.
SCAN_TIMEOUT_SECONDS = 10.0

#: What a blocked caller is told. One fixed sentence on purpose: the findings
#: stay in the audit log rather than echoing attacker-controlled text back.
REFUSAL_TEXT = "I can't help with that request — it was flagged by the security scanner."
SCANNER_UNAVAILABLE_TEXT = (
    "I can't process requests right now: the security scanner is unavailable. "
    "Nothing was sent to the model."
)

REASON_CLEAN = "clean"
REASON_FLAGGED = "flagged"
REASON_SCANNER_TIMEOUT = "scanner_timeout"
REASON_SCANNER_ERROR = "scanner_error"
REASON_BUDGET_EXCEEDED = "budget_exceeded"

_BOUNDARY_USER_INPUT = "user_input"
_BOUNDARY_TOOL_RESULT = "tool_result"


def new_gate_id() -> str:
    """One id per turn, correlating every decision that turn produces."""
    return f"gate-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class GateDecision:
    """One recorded verdict, with the provenance the audit row will carry."""

    allowed: bool
    reason: str
    findings: tuple[str, ...] = ()
    boundary: str = _BOUNDARY_USER_INPUT
    surface: str = ""
    gate_id: str = ""
    policy_version: str = POLICY_VERSION
    tool: str | None = None


def _record(decision: GateDecision, user_id: str) -> GateDecision:
    """Every decision — allow and refuse — lands in the audit log.

    'No path reaches `_execute_tool` without recorded gate decisions' means the
    allow rows exist too: a refusal proves the gate fired, but only a recorded
    allow proves a tool ran *through* one.
    """
    log_audit(
        "chat_gate_decision",
        user_id or "anonymous",
        detail={
            "gate_id": decision.gate_id,
            "surface": decision.surface,
            "boundary": decision.boundary,
            "reason": decision.reason,
            "allowed": decision.allowed,
            "findings": list(decision.findings[:20]),
            "tool": decision.tool,
            "policy_version": decision.policy_version,
        },
        severity="info" if decision.allowed else "warning",
    )
    return decision


async def gate_untrusted(
    payload: object,
    *,
    surface: str,
    user_id: str = "",
    boundary: str = _BOUNDARY_USER_INPUT,
    gate_id: str | None = None,
    tool: str | None = None,
    timeout: float | None = None,
) -> GateDecision:
    """Scan one untrusted payload, or refuse it with the reason it failed.

    `payload` is any JSON-ish structure; `scan_config` walks it and hands every
    string to the Warden at `boundary` (`user_input` for anything entering the
    process, `tool_result` for outputs re-fed to a model).
    """
    gid = gate_id or new_gate_id()
    # Read at call time, not as a defaulted argument: the timeout is policy,
    # and policy that a deployment or test can only change by editing source
    # is policy that never gets tuned.
    scan_timeout = SCAN_TIMEOUT_SECONDS if timeout is None else timeout

    def _decision(allowed: bool, reason: str, findings: tuple[str, ...] = ()) -> GateDecision:
        return GateDecision(
            allowed=allowed,
            reason=reason,
            findings=findings,
            boundary=boundary,
            surface=surface,
            gate_id=gid,
            tool=tool,
        )

    try:
        verdict = await asyncio.wait_for(
            scan_config(payload, boundary=boundary), timeout=scan_timeout
        )
    except TimeoutError:
        return _record(_decision(False, REASON_SCANNER_TIMEOUT), user_id)
    except ScanBudgetExceeded:
        return _record(_decision(False, REASON_BUDGET_EXCEEDED), user_id)
    except Exception:
        # The scanner failing is not a pass. Catching `Exception` broadly is
        # the policy: anything the detector raises means "no verdict", and no
        # verdict means the turn does not proceed.
        return _record(_decision(False, REASON_SCANNER_ERROR), user_id)

    if not isinstance(verdict, dict):
        return _record(_decision(False, REASON_SCANNER_ERROR), user_id)
    status = verdict.get("status")
    if status == "clean":
        return _record(_decision(True, REASON_CLEAN), user_id)
    if status == "flagged":
        findings = tuple(str(f) for f in verdict.get("findings", [])[:20])
        return _record(_decision(False, REASON_FLAGGED, findings), user_id)
    # A dict that is not a verdict is malformed scanner output: fail closed.
    return _record(_decision(False, REASON_SCANNER_ERROR), user_id)


def refusal_content(decision: GateDecision) -> str:
    """The assistant-visible text for a refused turn."""
    if decision.reason in (REASON_SCANNER_TIMEOUT, REASON_SCANNER_ERROR):
        return SCANNER_UNAVAILABLE_TEXT
    return REFUSAL_TEXT


def openai_refusal(decision: GateDecision) -> dict[str, Any]:
    """A refused turn as an ordinary OpenAI-shaped assistant answer.

    The engine's `/v1/chat/completions` (#150) answers a Gate block the same
    way: a refusal is a normal answer carrying `finish_reason="content_filter"`,
    not a 500, and it never reaches an agent. Conductor's chat surfaces use
    the same shape so clients read one refusal convention everywhere.
    """
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": refusal_content(decision)},
                "finish_reason": "content_filter",
            }
        ],
        "model": "chat-gate",
        "security": {
            "gate_id": decision.gate_id,
            "reason": decision.reason,
            "policy_version": decision.policy_version,
        },
    }


# ── Tool effect policy ───────────────────────────────────────────────────────
#
# Classification of the tools the chat loop can dispatch. Destinations,
# credentials, and side effects are owned server-side; what the model selects
# is only the name and declarative arguments.

#: Effects that remove or destroy state. Approval required, always.
TOOL_EFFECT_DESTROY = "destroy"
#: Effects that create or mutate durable state. Approval required.
TOOL_EFFECT_MUTATE = "mutate"
#: Effects that leave the process over the network (reads or subrequests).
#: Requires an authenticated principal.
TOOL_EFFECT_NETWORK = "network"
#: Local, user-scoped reads.
TOOL_EFFECT_READ = "read"

TOOL_EFFECTS: dict[str, str] = {
    # read
    "query_metrics": TOOL_EFFECT_READ,
    "list_agent_buttons": TOOL_EFFECT_READ,
    "memory_search": TOOL_EFFECT_READ,
    "profile_get": TOOL_EFFECT_READ,
    "list_workflows": TOOL_EFFECT_READ,
    "suggest_widgets": TOOL_EFFECT_READ,
    "suggest_workflows": TOOL_EFFECT_READ,
    # network — a principal is the authorization
    "poll_jira": TOOL_EFFECT_NETWORK,
    "fetch_program_state": TOOL_EFFECT_NETWORK,
    "search_jira": TOOL_EFFECT_NETWORK,
    "get_issue": TOOL_EFFECT_NETWORK,
    "get_jira_issue": TOOL_EFFECT_NETWORK,
    "check_blockers": TOOL_EFFECT_NETWORK,
    "detect_blockers": TOOL_EFFECT_NETWORK,
    "scan_risks": TOOL_EFFECT_NETWORK,
    "generate_exec_summary": TOOL_EFFECT_NETWORK,
    "search_confluence": TOOL_EFFECT_NETWORK,
    "airtable_query": TOOL_EFFECT_NETWORK,
    "airtable_describe": TOOL_EFFECT_NETWORK,
    "web_search": TOOL_EFFECT_NETWORK,
    "browse_url": TOOL_EFFECT_NETWORK,
    "analyze_dashboard": TOOL_EFFECT_NETWORK,
    "run_workflow": TOOL_EFFECT_NETWORK,
    # mutate — privileged effect, approval independent of the model required
    "save_as_action": TOOL_EFFECT_MUTATE,
    "create_agent_button": TOOL_EFFECT_MUTATE,
    "modify_agent_button": TOOL_EFFECT_MUTATE,
    "create_dashboard_widget": TOOL_EFFECT_MUTATE,
    "memory_add": TOOL_EFFECT_MUTATE,
    "memory_edit": TOOL_EFFECT_MUTATE,
    "profile_set": TOOL_EFFECT_MUTATE,
    "create_workflow": TOOL_EFFECT_MUTATE,
    "update_eval": TOOL_EFFECT_MUTATE,
    "favorite_model": TOOL_EFFECT_MUTATE,
    "hill_climb": TOOL_EFFECT_MUTATE,
    "mutate_workflow": TOOL_EFFECT_MUTATE,
    # destroy — privileged effect, approval independent of the model required
    "remove_agent_button": TOOL_EFFECT_DESTROY,
    "memory_delete": TOOL_EFFECT_DESTROY,
    "profile_delete": TOOL_EFFECT_DESTROY,
}


def tool_effect(tool_name: str) -> str:
    """The effect class of one tool. Unknown tools carry the strictest class
    that exists, because the table is the registry: a name outside it is not
    a tool the chat loop was ever authorized to run."""
    return TOOL_EFFECTS.get(tool_name, TOOL_EFFECT_DESTROY)


def gate_tool_dispatch(
    tool_name: str, user_id: str, *, approved: bool = False, gate_id: str | None = None
) -> GateDecision | None:
    """The authorization decision for dispatching one tool, or None to run.

    This is the 'independent of model judgment' half of the gate: the model
    cannot mint an approval or a principal, so a refusal here cannot be
    prompted around. Scanning of the tool's own arguments is separate (they
    cross the user_input boundary in the loop).
    """
    effect = tool_effect(tool_name)
    if effect in (TOOL_EFFECT_DESTROY, TOOL_EFFECT_MUTATE):
        if approved:
            log_audit(
                "chat_tool_privilege_approved",
                user_id or "anonymous",
                target=tool_name,
                detail={
                    "gate_id": gate_id or new_gate_id(),
                    "effect": effect,
                    "policy_version": POLICY_VERSION,
                },
            )
            return None
        decision = GateDecision(
            allowed=False,
            reason="approval_required",
            boundary=_BOUNDARY_USER_INPUT,
            surface="chat_tool_dispatch",
            gate_id=gate_id or new_gate_id(),
            tool=tool_name,
        )
        log_audit(
            "chat_tool_privilege_blocked",
            user_id or "anonymous",
            target=tool_name,
            detail={
                "gate_id": decision.gate_id,
                "effect": effect,
                "policy_version": POLICY_VERSION,
            },
            severity="warning",
        )
        return decision
    if effect == TOOL_EFFECT_NETWORK and not user_id:
        decision = GateDecision(
            allowed=False,
            reason="principal_required",
            boundary=_BOUNDARY_USER_INPUT,
            surface="chat_tool_dispatch",
            gate_id=gate_id or new_gate_id(),
            tool=tool_name,
        )
        log_audit(
            "chat_tool_no_principal",
            "anonymous",
            target=tool_name,
            detail={"gate_id": decision.gate_id, "policy_version": POLICY_VERSION},
            severity="warning",
        )
        return decision
    return None
