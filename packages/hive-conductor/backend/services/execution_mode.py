"""Host-resolved isolation floor for one graph node (#60, #845).

The authorization decision stays with Sentinel: this module never decides
whether an action is permitted, it only translates the tier Sentinel resolved
into the Conductor's isolation vocabulary ("blocked" / "async" / "sandbox").

The vocabulary is the adapter's, not the core's: "async" means the node runs
in-process under the governed runtime, "sandbox" means it runs in the
subprocess/Hyperlight path. Keeping the mapping here is what lets the core
expose one policy decision (``Sentinel.authorize`` plus
``Sentinel.resolve_tier``) without owning a second, adapter-shaped notion of
execution.

Two rules follow from the host tier record, never from a caller label:

* "blocked" is reserved for a host DENIAL -- a permission miss (fail-closed
  table/source) or an explicit ``Tier.BLOCKED`` entry.
* an authorized action runs at the isolation floor of the tier the host policy
  resolved. Tiers whose human decision is not (yet) cleared run at the
  "sandbox" floor, never inline; only an explicit ``Tier.OPEN`` or
  ``Tier.ROLE_AUTO`` host record selects the inline ("async") mode.
* ``authorized`` only means the principal holds the underlying capability. A
  decision whose ``needs`` is not "none" still awaits the required human
  approval, so it never takes the inline floor no matter what a caller
  default re-resolves to -- it stays parked at the sandbox floor.

A deployment's permission grant for the action is itself the host policy
record that makes graph-node execution reachable: without one, the fail-closed
table denies and every node blocks (#1165 posture).
"""

from __future__ import annotations

from typing import Any

from maistro.security.sentinel.authz_types import Principal, Tier


def resolve_execution_mode(
    sentinel: Any,
    action: str,
    principal: Principal,
    *,
    reversibility: str = "reversible",
    default: Tier | None = None,
) -> str:
    """Map a host-resolved tier to this adapter's isolation floor."""
    tier = sentinel.resolve_tier(action, principal, reversibility=reversibility, default=default)
    if tier == Tier.BLOCKED:
        return "blocked"
    if tier in (Tier.OPEN, Tier.ROLE_AUTO):
        return "async"
    return "sandbox"


async def resolve_authorized_execution_mode(
    sentinel: Any,
    action: str,
    principal: Principal,
    *,
    args: dict[str, Any] | None = None,
    reversibility: str = "irreversible",
    default: Tier | None = None,
) -> str:
    """Resolve the isolation floor for an action Sentinel has just judged.

    A denial is "blocked" and nothing else is: the tier floor never turns a
    denial into a weaker mode, and never turns an authorization into a
    stronger one than the host record allows. An authorization with an
    outstanding ``needs`` (self-elevation / scoped 2FA / delegated / admin)
    has not cleared the required human approval yet, so it is parked at the
    sandbox floor -- the caller's ``default`` cannot promote it inline.
    """
    decision = await sentinel.authorize(
        action,
        principal,
        reversibility=reversibility,
        args=args,
    )
    if not decision.authorized:
        return "blocked"
    mode = resolve_execution_mode(
        sentinel,
        action,
        principal,
        reversibility=reversibility,
        default=default,
    )
    if mode == "async" and decision.needs != "none":
        # Sentinel judged this call against an approval-requiring tier (it
        # resolves without ``default``), so the uncleared human decision --
        # not the caller's default -- decides the floor. Park it in the
        # governed sandbox; it never executes inline pre-approval.
        return "sandbox"
    return mode
