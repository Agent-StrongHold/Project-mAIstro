"""Declaration → grant resolution: least authority, both directions (#974).

The manifest *declares* what a host may consider granting; the grant is what
the host actually hands the extension. Two rules, from the lifecycle guide:

- the host may grant less than declared (operator policy, user consent,
  least authority);
- the host never grants what was not declared — extension code cannot
  receive undeclared authority merely by importing SDK objects, because
  authority flows from the manifest, not from the import.

`GrantPolicy` is the harness's operator-policy seam: an optional restriction
applied on top of a manifest's declaration. It can only shrink; a policy
that names anything the manifest did not declare is a configuration error
and fails loudly rather than silently widening authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro_ext_harness.contract import ContractError
from maistro_ext_harness.manifest import ExtensionManifest

__all__ = ["Grant", "GrantPolicy", "GrantPolicyError", "resolve_grants"]


class GrantPolicyError(ContractError):
    """A grant policy names authority the manifest never declared."""


@dataclass(frozen=True)
class Grant:
    """The authority a host hands one loaded extension.

    Derived from a validated manifest's declarations, possibly narrowed by a
    `GrantPolicy` — never widened. `equals_declaration` is the property the
    security cases assert: the context an extension receives exposes exactly
    this set, so a grant that shrank the declaration is observable from
    inside the extension.
    """

    capabilities: frozenset[str]
    effects: frozenset[str]
    data_scopes: frozenset[str]
    network_allow: tuple[str, ...]
    network_ports: tuple[int, ...]
    filesystem_paths: tuple[str, ...]
    filesystem_mode: str
    secrets: tuple[str, ...]

    def has_capability(self, name: str) -> bool:
        """Whether `name` is granted. The only capability probe a handler gets."""
        return name in self.capabilities

    def equals_declaration(self, manifest: ExtensionManifest) -> bool:
        """Whether nothing was narrowed — the full declaration became the grant."""
        return (
            self.capabilities == frozenset(manifest.capabilities)
            and self.effects == frozenset(manifest.effects)
            and self.data_scopes == frozenset(manifest.data_scopes)
            and self.network_allow == manifest.network_allow
            and self.network_ports == manifest.network_ports
            and self.filesystem_paths == manifest.filesystem_paths
            and self.filesystem_mode == manifest.filesystem_mode
            and self.secrets == manifest.secrets
        )


@dataclass(frozen=True)
class GrantPolicy:
    """Operator-side narrowing applied over a manifest's declaration.

    Every field is an allow-list; `None` means "no narrowing for this axis".
    A policy is a *restriction*, so a name the manifest did not declare is a
    policy typo with security consequences and raises `GrantPolicyError` —
    it must not silently become a grant of nothing (hiding the typo) or,
    worse, be reinterpreted as a declaration.
    """

    capabilities: frozenset[str] | None = None
    effects: frozenset[str] | None = None
    data_scopes: frozenset[str] | None = None


def _narrow(axis: str, declared: frozenset[str], allowed: frozenset[str] | None) -> frozenset[str]:
    if allowed is None:
        return declared
    undeclared = sorted(allowed - declared)
    if undeclared:
        raise GrantPolicyError(
            f"grant policy {axis} name(s) {undeclared} the manifest never declared; "
            "a policy narrows a declaration, it never adds to one"
        )
    return declared & allowed


def resolve_grants(manifest: ExtensionManifest, policy: GrantPolicy | None = None) -> Grant:
    """Turn a validated declaration into the grant a host hands the extension.

    With no policy the full declaration becomes the grant. With one, each
    axis intersects (and the intersection is checked to be a true subset —
    see `GrantPolicy`).
    """
    return Grant(
        capabilities=_narrow(
            "capability",
            frozenset(manifest.capabilities),
            policy.capabilities if policy else None,
        ),
        effects=_narrow("effect", frozenset(manifest.effects), policy.effects if policy else None),
        data_scopes=_narrow(
            "data scope",
            frozenset(manifest.data_scopes),
            policy.data_scopes if policy else None,
        ),
        network_allow=manifest.network_allow,
        network_ports=manifest.network_ports,
        filesystem_paths=manifest.filesystem_paths,
        filesystem_mode=manifest.filesystem_mode,
        secrets=manifest.secrets,
    )
