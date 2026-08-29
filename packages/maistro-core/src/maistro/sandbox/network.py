"""Sandbox egress: default-deny, and honest about what a tier can enforce (#77).

Two things this separates that are easy to conflate.

**`maistro.security.ssrf` guards the engine's own outbound calls.** It resolves
a URL and refuses private, loopback, link-local and cloud-metadata addresses.
That is the right guard for code this repository runs — and it is worth nothing
against candidate code, which is not obliged to go through Python at all. A
model-authored script can open a socket.

**This guards the sandbox.** The boundary is the network namespace, so "no
network" means the kernel has not given the sandbox an interface to use, not
that something declined to make a request.

The second distinction is what a tier can actually enforce. Bubblewrap offers
exactly two states: a private empty namespace, or the host's namespace shared
whole. It has no way to permit `api.example.com` and refuse everything else. So
`SCOPED` is a grant this backend must **refuse** rather than approximate, and
`_ScopedEgressUnsupported` says so at selection time instead of silently
handing over unrestricted host networking — which is what an implementation
that treated "scoped" as "on" would do.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger("maistro.sandbox.network")


class EgressMode(StrEnum):
    """How much network a workload is granted."""

    #: No interface at all. The default, and the only mode an unattended
    #: candidate gets without an explicit, reasoned grant.
    DENY = "deny"
    #: A specific allowlist of destinations. Requires a backend that can filter.
    SCOPED = "scoped"
    #: The host's network namespace, whole. Unscoped and unfiltered.
    HOST = "host"


class EgressNotEnforceableError(RuntimeError):
    """Raised when a backend cannot enforce the egress the policy asked for."""


@dataclass(frozen=True)
class EgressGrant:
    """An explicit, reasoned network grant. Absent means denied.

    Frozen, and carried on the frozen `SandboxConfig`, because "cannot be
    widened by candidate code" is only true if there is nothing to widen: the
    grant is decided before the sandbox exists and there is no API that edits
    it afterwards.
    """

    mode: EgressMode = EgressMode.DENY
    #: Destinations for `SCOPED`. Meaningless in the other modes.
    allow: tuple[str, ...] = field(default_factory=tuple)
    #: Why this workload is allowed out. Required for anything but DENY, so a
    #: grant cannot be made by accident and an audit line always has a subject.
    reason: str = ""

    def __post_init__(self) -> None:
        if self.mode is not EgressMode.DENY and not self.reason:
            raise ValueError(f"an egress grant of {self.mode.value!r} requires a reason")
        if self.mode is EgressMode.SCOPED and not self.allow:
            raise ValueError("a scoped egress grant requires at least one destination")
        if self.mode is not EgressMode.SCOPED and self.allow:
            raise ValueError(f"{self.mode.value!r} egress does not take an allowlist")

    @property
    def grants_network(self) -> bool:
        return self.mode is not EgressMode.DENY


#: The default every sandbox gets unless a policy says otherwise.
DENY_ALL = EgressGrant()


def resolve_grant(
    grant: EgressGrant,
    *,
    backend_name: str,
    supports_scoped_egress: bool,
    sandbox_id: str,
) -> EgressGrant:
    """Check the grant against what the backend can enforce, and record it.

    Refusing is the point. A backend that cannot filter destinations and is
    handed a `SCOPED` grant has two options: give the sandbox the whole host
    network and call it scoped, or refuse. The first is the failure this issue
    exists to prevent, and it would be invisible — the audit line would say
    "scoped" while the sandbox had unrestricted egress.
    """
    if grant.mode is EgressMode.SCOPED and not supports_scoped_egress:
        raise EgressNotEnforceableError(
            f"backend {backend_name!r} cannot filter egress destinations, so it cannot honour a "
            f"scoped grant for {list(grant.allow)}; it would have to grant the whole host network. "
            "Use a backend that can filter, or state the grant as 'host' if that is intended."
        )
    if grant.grants_network:
        logger.warning(
            "sandbox_egress_granted id=%s backend=%s mode=%s allow=%s reason=%s",
            sandbox_id,
            backend_name,
            grant.mode.value,
            ",".join(grant.allow) or "-",
            grant.reason,
        )
    else:
        logger.info("sandbox_egress_denied id=%s backend=%s", sandbox_id, backend_name)
    return grant


__all__ = [
    "DENY_ALL",
    "EgressGrant",
    "EgressMode",
    "EgressNotEnforceableError",
    "resolve_grant",
]
