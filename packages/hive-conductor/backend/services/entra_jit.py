"""Entra group-gated JIT account provisioning at the login boundary (#492).

`services.entra_entitlements` is the deterministic policy engine; this module
is the product transaction its docstring promised: after #491's verified
Entra identity and an authoritative current-membership read have both been
established, an *unlinked* identity may be admitted as a new local account
only when it belongs to an explicitly configured eligible group, and the
account receives only the permissions that group's mapping grants.

Security posture (mirrors the policy engine's):

- Disabled by default; an unlinked Entra identity is refused unchanged.
- Membership is decided per login on a fresh Microsoft Graph
  ``transitiveMemberOf`` read, never on optional/truncatable token claims.
  A directory outage refuses login — it never degrades into "no groups".
- The account is ``role="user"`` with an unusable password hash, so JIT
  accounts authenticate through Entra only; admin is never created via OAuth.
- Group removal therefore blocks the *next* first-login attempt, but already
  provisioned accounts keep their grants until an explicit reconciliation
  surface ships — see KNOWN-GAPS.md; nothing here revokes silently.
- Every decision (admit or deny) is audited with the policy version and the
  matched group IDs, so an admission can always be reconstructed.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import stores
from config import Settings
from models.schemas import HiveUser
from routes.audit import log_audit

from maistro.auth.entra import ENTRA_PROVIDER_NAME
from maistro.http import get_shared_client
from maistro.security.outbound import configure_outbound_policy
from services.entra_entitlements import (
    EntraGroupGrant,
    EntraGroupMembership,
    EntraJitPolicy,
    IncompleteGroupMembershipError,
    jit_policy_from_config,
)

if TYPE_CHECKING:
    from maistro.auth.oauth import OAuthExchange, OAuthIdentity
    from services.oauth_login import HiveIdentityLinkStore

__all__ = [
    "ENTRA_JIT_UNUSABLE_PASSWORD_HASH",
    "EntraJitProvisioner",
    "GraphMembershipResolver",
    "build_entra_jit_provisioner",
]

#: `verify_password` fails closed on any stored value that carries neither a
#: known Argon2id nor a bcrypt prefix, so this marker disables password login
#: for JIT accounts while leaving the field non-empty and self-describing.
ENTRA_JIT_UNUSABLE_PASSWORD_HASH = "!entra-jit"

_GRAPH_ORIGIN = "https://graph.microsoft.com"
_GRAPH_MEMBER_OF_URL = f"{_GRAPH_ORIGIN}/v1.0/me/transitiveMemberOf"
_GRAPH_PAGE_SIZE = 999
#: Bound the membership read the way the token-claim path is bounded: a
#: directory that pages forever is indistinguishable from a directory that
#: cannot answer, and both must refuse rather than admit on partial data.
_GRAPH_MAX_PAGES = 10

#: Local usernames are presentation-free identifiers (registry claims are
#: casefolded); keep the JIT-derived form conservative and short.
_JIT_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,62}[A-Za-z0-9]$")


class GraphMembershipResolver:
    """Authoritative current Entra group membership via Microsoft Graph.

    The verified id_token proves identity, not membership: group claims are
    optional, truncatable, and overage-prone, so admission is decided on this
    fresh read taken with the login's access token. Any transport, schema, or
    pagination failure raises :class:`IncompleteGroupMembershipError` — the
    same refusal the policy engine gives incomplete token evidence.
    """

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or get_shared_client(timeout=10.0, follow_redirects=False)
        # Same reason as `OAuth2Client`: the Graph origin arrives as a
        # constructor constant rather than through settings, so the outbound
        # policy (#155) cannot have seen it. An allowance is one exact origin.
        configure_outbound_policy(_GRAPH_ORIGIN)

    async def _fetch_page(self, url: str, access_token: str) -> dict[str, object]:
        try:
            response = await self._http.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.HTTPError as exc:
            raise IncompleteGroupMembershipError(
                f"Graph membership read failed: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise IncompleteGroupMembershipError(
                f"Graph membership read returned http {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IncompleteGroupMembershipError("Graph membership read was not JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise IncompleteGroupMembershipError("Graph membership read had no value list")
        return payload

    async def resolve(self, access_token: str) -> EntraGroupMembership:
        """Complete, de-duplicated group object IDs for the token's subject."""
        url = f"{_GRAPH_MEMBER_OF_URL}?$select=id,@odata.type&$top={_GRAPH_PAGE_SIZE}"
        group_ids: list[str] = []
        for _page in range(_GRAPH_MAX_PAGES):
            payload = await self._fetch_page(url, access_token)
            for item in payload["value"]:  # type: ignore[index]
                if not isinstance(item, dict):
                    raise IncompleteGroupMembershipError("Graph membership item was not an object")
                # transitiveMemberOf lists directory objects; only groups map
                # to grants, and anything else (an administrative unit, a role
                # template) must not be name-collided into one.
                if not str(item.get("@odata.type", "")).endswith("graph.group"):
                    continue
                group_id = item.get("id")
                if not isinstance(group_id, str) or not group_id.strip():
                    raise IncompleteGroupMembershipError("Graph group item had no id")
                group_ids.append(group_id.strip())
            next_link = payload.get("@odata.nextLink")
            if not isinstance(next_link, str) or not next_link.strip():
                return EntraGroupMembership.complete_resolver(group_ids)
            url = next_link.strip()
        raise IncompleteGroupMembershipError(
            f"Graph membership read exceeded {_GRAPH_MAX_PAGES} pages"
        )


def _candidate_username(identity: OAuthIdentity) -> str:
    """A conservative local username derived from verified identity data.

    The display name is the operator-facing choice and the email local part
    the familiar one; when neither survives sanitizing (or is present), the
    immutable tenant:object subject's object id is used, so the same person
    always derives the same fallback rather than a random one.
    """
    display = (identity.display_name or "").strip()
    email_local = (identity.email or "").split("@", 1)[0].strip()
    for source in (display, email_local):
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", source).strip("._-")
        if _JIT_USERNAME_RE.fullmatch(cleaned):
            return cleaned
    object_id = identity.sub.rsplit(":", 1)[-1]
    return f"entra-{object_id[:36]}"


class EntraJitProvisioner:
    """The #492 product transaction: group-gated first-login account creation.

    Returns the provisioned (or canonically linked) :class:`HiveUser` on
    admission and ``None`` on any refusal; every outcome is audited. Never
    raises for policy or membership refusals — those are decisions, not
    faults — so the login seam can stay a single branch.
    """

    def __init__(
        self,
        policy: EntraJitPolicy,
        resolver: GraphMembershipResolver,
        *,
        links: HiveIdentityLinkStore | None = None,
    ) -> None:
        self._policy = policy
        self._resolver = resolver
        self._links = links

    def applies_to(self, provider: str) -> bool:
        """JIT is the Entra specialization; generic OIDC providers never JIT."""
        return provider == ENTRA_PROVIDER_NAME

    async def provision(self, identity: OAuthIdentity, exchange: OAuthExchange) -> HiveUser | None:
        # Lazy import: oauth_login imports this module at its own top level.
        from services import username_registry
        from services.oauth_login import HiveIdentityLinkStore, IdentityLinkConflictError

        try:
            membership = await self._resolver.resolve(exchange.token.access_token)
        except IncompleteGroupMembershipError as exc:
            log_audit(
                "auth.entra.jit",
                identity.sub,
                target="entra",
                detail={
                    "provider": "entra",
                    "reason": "incomplete_membership",
                    "detail": str(exc),
                },
                severity="warning",
            )
            return None

        decision = self._policy.evaluate(membership)
        if not decision.eligible or decision.managed is None:
            log_audit(
                "auth.entra.jit",
                identity.sub,
                target="entra",
                detail={
                    "provider": "entra",
                    "reason": "not_eligible",
                    "policy_version": self._policy.policy_version,
                },
                severity="warning",
            )
            return None
        managed = decision.managed

        username = _candidate_username(identity)
        user = HiveUser(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=ENTRA_JIT_UNUSABLE_PASSWORD_HASH,
            role="user",
            is_active=True,
            permissions=sorted(managed.permissions),
            did=None,
            created_at=datetime.now(UTC),
        )
        try:
            username_registry.create_users([user])
        except username_registry.UsernameTakenError:
            # Fail closed and loud: guessing a suffix would hand one person a
            # second, differently-named account and the operator no signal.
            log_audit(
                "auth.entra.jit",
                identity.sub,
                target="entra",
                detail={
                    "provider": "entra",
                    "reason": "username_conflict",
                    "username": username,
                    "policy_version": managed.policy_version,
                },
                severity="warning",
            )
            return None
        except username_registry.UsernameAllocationError as exc:
            log_audit(
                "auth.entra.jit",
                identity.sub,
                target="entra",
                detail={
                    "provider": "entra",
                    "reason": "allocation_failed",
                    "detail": str(exc),
                },
                severity="warning",
            )
            return None

        links = self._links or HiveIdentityLinkStore()
        try:
            await links.link("entra", identity.sub, user.id)
        except IdentityLinkConflictError:
            # A concurrent login won the identity link. Keep the canonical
            # account it points at and roll this duplicate allocation back,
            # so one human never holds two JIT accounts.
            username_registry.rollback_users([user])
            existing_id = await links.resolve("entra", identity.sub)
            existing = stores.users.get(existing_id) if existing_id else None
            if existing is not None and existing.is_active:
                log_audit(
                    "auth.entra.jit",
                    existing.id,
                    target="entra",
                    detail={
                        "provider": "entra",
                        "reason": "superseded_by_existing_link",
                        "subject": identity.sub,
                        "policy_version": managed.policy_version,
                    },
                )
                return existing
            log_audit(
                "auth.entra.jit",
                identity.sub,
                target="entra",
                detail={
                    "provider": "entra",
                    "reason": "link_conflict_without_account",
                    "subject": identity.sub,
                },
                severity="warning",
            )
            return None

        log_audit(
            "auth.entra.jit",
            user.id,
            target="entra",
            detail={
                "provider": "entra",
                "reason": "provisioned",
                "subject": identity.sub,
                "username": username,
                "policy_version": managed.policy_version,
                "matched_group_ids": list(managed.matched_group_ids),
                "permissions": sorted(managed.permissions),
                "membership_source": managed.membership_source,
            },
        )
        return user


def build_entra_jit_provisioner(
    settings: Settings,
    *,
    http: httpx.AsyncClient | None = None,
    links: HiveIdentityLinkStore | None = None,
    resolver: GraphMembershipResolver | None = None,
) -> EntraJitProvisioner | None:
    """The deployment's provisioner, or ``None`` when JIT is disabled.

    Settings validation has already run the mapping through the real policy
    engine at load time; building here re-validates for free, so the two can
    never disagree about whether a config is activatable.
    """
    if not settings.entra_jit_enabled:
        return None
    policy = jit_policy_from_config(
        enabled=True,
        policy_version=settings.entra_jit_policy_version,
        groups={
            group_id: EntraGroupGrant(role=grant.role, permissions=frozenset(grant.permissions))
            for group_id, grant in settings.entra_jit_groups.items()
        },
        allowed_permissions=settings.entra_jit_allowed_permissions,
    )
    return EntraJitProvisioner(
        policy,
        resolver or GraphMembershipResolver(http),
        links=links,
    )
