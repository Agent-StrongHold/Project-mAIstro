"""Governed UI/A2UI extension components that project canonical state only.

M9-F2 (issue #967, epic M9-F #943). Out-of-tree extension packages may add UI
components — A2UI-style declarative surface descriptors — to a running
product, without ever receiving their own execution, lifecycle,
authorization, or terminal-state truth. The client renders; the canonical
server owns truth; this module is the contract between the two.

Relationship to the A2UI adoption (ADR-070426-3a1f / SPEC-277): SPEC-277
governs the agent→UI flow (an agent strategy emitting surfaces into a chat
response). This module governs the *extension-pack*→UI flow: installed
extensions declaring components ahead of time. Both share the same trust
posture — declarative component data, client-side rendering, server-owned
state — and this contract's manifests are deliberately shaped so a component
descriptor can ride an A2UI surface unchanged.

The rules this module enforces, each pinned by a test in
``packages/maistro-core/tests/extensions/test_ui_components.py``:

* **Rendering is projection, not store access.** A UI extension ships a
  manifest of *data*: components, data bindings, action intents, sandbox
  policy, asset digests. It names no store, holds no session, and cannot
  import one — the host reads canonical state and hands the service plain
  snapshots (:meth:`UiProjectionService.render`). Bindings may reference
  only the closed, non-sensitive canonical field allowlist
  (:data:`BINDABLE_FIELDS`); anything else fails inspection.
* **Mutating actions can only name governed server seams.** The intent
  vocabulary is closed (:data:`GOVERNED_ROUTES`): cancel a Run, settle or
  abandon a durable HITL pause, admit a Task. Every mutating action's route
  is pinned to the canonical API seam that carries it, and canonical path
  parameters are resolved from the host-supplied canonical snapshot — never
  from the client payload. There is deliberately no "mark run/goal complete"
  intent: completion is canonical execution truth, written by the executor
  and reconciler, not a UI action. Widening :data:`GOVERNED_ROUTES` is a
  reviewed core change, never a manifest or configuration act.
* **Disabled and unauthorized are enforced, not merely hidden.** The same
  availability evaluation backs both :meth:`UiProjectionService.render`
  (what the client may show) and :meth:`UiProjectionService.dispatch` (what
  the server will honor). A disabled extension, a missing principal
  permission, an authority the extension's own governed grant does not
  cover, an unmet canonical precondition, or an unresolvable canonical
  target each make an action unavailable — and ``dispatch`` re-runs every
  check server-side at invocation time, so a client that forged
  ``available: true`` into rendered metadata gains nothing.
* **Component state loss cannot move canonical state.** ``render`` is a pure
  function of the manifest and the supplied snapshot; reloading re-projects
  from a fresh canonical read. ``dispatch`` refuses client arguments that
  carry canonical field or binding names (:class:`ClientStateRejected`): a
  component re-posting its last-known canonical state can never rewrite what
  it displays.
* **No unrestricted scripts or network outside declared policy.** Every
  component declares a :class:`SandboxPolicy`. Inspection rejects injection
  vectors in component text (script tags, ``javascript:`` URIs, inline
  event handlers, ``eval``), unsafe CSP tokens (``'unsafe-inline'``,
  ``'unsafe-eval'``, wildcards, ``data:``/``blob:`` sources, plaintext
  HTTP), and any outbound target — ``open_url`` or otherwise — outside the
  declared origin allowlist. The rendered metadata carries the header-ready
  CSP so the hosting client can sandbox the surface mechanically.
* **Provenance is inspectable in rendered metadata.** Every rendered
  component and every resolved action call carries the catalog id, component
  id, semantic version, publisher, and the SHA-256 of the exact manifest
  bytes it was projected from (:class:`ComponentProvenance`).

Nothing in this module executes extension code: a UI extension manifest is
data, inspection never imports anything, and the only authority in the loop
is the host's own authorization inputs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import SplitResult, urlsplit

from maistro.extensions.manifest import SEMVER_RE, sha256_hex
from maistro.extensions.types import ExtensionScope
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus

__all__ = [
    "BINDABLE_FIELDS",
    "GOVERNED_ROUTES",
    "LOCAL_INTENTS",
    "MUTATING_INTENTS",
    "PRECONDITIONS",
    "SUPPORTED_STATE_KINDS",
    "UI_MANIFEST_VERSION",
    "ActionAvailability",
    "ActionUnavailable",
    "CanonicalStateKind",
    "CatalogRejected",
    "ClientStateRejected",
    "ComponentAsset",
    "ComponentProvenance",
    "DataBinding",
    "ExtensionActiveCheck",
    "GovernedActionCall",
    "GovernedRoute",
    "RenderedComponent",
    "RouteParam",
    "SandboxPolicy",
    "UiAction",
    "UiComponentDefinition",
    "UiComponentManifest",
    "UiExtensionError",
    "UiProjectionService",
    "UnknownAction",
    "UnknownCatalog",
    "UnknownComponent",
    "assert_ui_snapshot_intact",
    "inspect_ui_manifest",
    "verify_component_asset",
]

#: The only UI component manifest envelope this platform accepts. Unknown
#: versions fail closed: a forward-compat guess would render surfaces nobody
#: reviewed.
UI_MANIFEST_VERSION = 1

CanonicalStateKind = Literal["workspace", "goal", "graph", "run", "node_run", "attempt", "artifact"]
#: The canonical state kinds a component binding may reference: the
#: Workspace plus the ``Goal -> Graph -> Run -> NodeRun -> Attempt`` spine and
#: its Artifacts. Anything else is not canonical state and cannot be bound.
SUPPORTED_STATE_KINDS: frozenset[str] = frozenset(
    {"workspace", "goal", "graph", "run", "node_run", "attempt", "artifact"}
)

#: The projection allowlist: the only canonical fields a binding may name,
#: per kind. Deliberately narrower than the canonical models — identity,
#: human-visible descriptors, and lifecycle status only. Payloads
#: (``result``), storage locations, provenance payloads, leases, and principal
#: identifiers are never projectable: a UI component renders what happened,
#: not the contents or the plumbing underneath it. Extending this table is a
#: reviewed core change, never a manifest act.
BINDABLE_FIELDS: Mapping[str, tuple[str, ...]] = {
    # maistro.workspaces.model.Workspace
    "workspace": ("workspace_id", "name", "description"),
    # maistro.interop canonical Goal identity: goal_id + goal_revision.
    "goal": ("goal_id", "goal_revision"),
    # maistro.graph.definitions.Graph (content_hash is the snapshot identity).
    "graph": ("graph_id", "name", "description", "content_hash"),
    # maistro.runs.model.Run
    "run": (
        "run_id",
        "workspace_id",
        "project_id",
        "status",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "error",
    ),
    # maistro.runs.model.NodeRun
    "node_run": (
        "node_run_id",
        "run_id",
        "node_id",
        "ordinal",
        "status",
        "created_at",
        "updated_at",
    ),
    # maistro.runs.model.Attempt
    "attempt": ("attempt_id", "node_run_id", "ordinal", "status"),
    # maistro.builders.contracts.ArtifactRef (path stays host-side).
    "artifact": ("artifact_id", "type", "content_type", "version", "producer"),
}

#: Run status values (as strings) from which a Run can still be cancelled —
#: everything outside the canonical terminal set. Derived from
#: ``maistro.runs.model`` so this vocabulary cannot drift from the canonical
#: execution lifecycle.
_CANCELLABLE_RUN_STATUSES: frozenset[str] = frozenset(
    status.value for status in RunStatus if status not in TERMINAL_RUN_STATUSES
)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class UiExtensionError(RuntimeError):
    """Base class for governed UI extension component failures."""


class CatalogRejected(UiExtensionError):
    """The UI catalog manifest bytes are not a valid, governable catalog.

    Raised only from parsing — malformed, unsafe, or ungovernable manifests
    have no catalog identity to project and fail at the door.
    """


class UnknownCatalog(UiExtensionError):
    """No UI component catalog is registered under the requested extension id."""


class UnknownComponent(UiExtensionError):
    """The catalog declares no component under the requested component id."""


class UnknownAction(UiExtensionError):
    """The component declares no action under the requested action name."""


class ActionUnavailable(UiExtensionError):
    """A dispatched action is not available in the server-evaluated state.

    Raised by :meth:`UiProjectionService.dispatch` — the server-side
    enforcement point. Rendered availability metadata is advisory; this is
    the check that decides.
    """


class ClientStateRejected(UiExtensionError):
    """Client action arguments tried to carry canonical state.

    A component's local state (form drafts, last-rendered canonical values)
    is never authoritative: canonical targeting and canonical fields always
    come from the host's own snapshot, so a reload or a stale client cannot
    replay state back into the execution spine.
    """


# --------------------------------------------------------------------------
# Governed action routes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteParam:
    """One canonical path parameter of a governed route.

    ``name`` is the path template variable; ``(kind, field)`` names the
    canonical field the value is resolved from, in the host-supplied
    snapshot. Clients cannot supply these values.
    """

    name: str
    kind: CanonicalStateKind
    field: str


@dataclass(frozen=True)
class GovernedRoute:
    """One canonical server seam a mutating UI action may target.

    The table (:data:`GOVERNED_ROUTES`) is closed. Each entry names a real
    canonical API seam — the same routes the product's HTTP API serves — so
    a UI action is literally a governed server call, not a side channel.

    ``required_permissions`` is canonical authority, not catalog-chosen
    labeling: a mutating action must declare exactly this set, so a
    component can never dress up a governed mutation in a permission the
    operator never tied to it.
    """

    intent: str
    method: str
    path: str
    required_permissions: tuple[str, ...]
    params: tuple[RouteParam, ...] = ()

    def resolved_path(self, canonical_state: Mapping[str, Any]) -> str | None:
        """Substitute canonical path parameters from a canonical snapshot.

        Returns ``None`` when any parameter's canonical value is missing or
        blank — the action cannot target anything, which the caller surfaces
        as unavailability rather than a malformed request.
        """
        resolved = self.path
        for param in self.params:
            value = _field_value(canonical_state.get(param.kind), param.field)
            if not isinstance(value, str) or not value.strip():
                return None
            resolved = resolved.replace("{" + param.name + "}", value)
        return resolved


#: The closed table of governed seams. Cancelling a Run, settling or
#: abandoning a durable HITL pause, and admitting a Task are the only
#: mutations a UI component can express. There is no completion route on
#: purpose: Runs and Goals are completed by the canonical executor and
#: reconciler, never by a client-rendered button.
GOVERNED_ROUTES: Mapping[str, GovernedRoute] = MappingProxyType(
    {
        "cancel_run": GovernedRoute(
            intent="cancel_run",
            method="POST",
            path="/v1/dag-runs/{run_id}/cancel",
            required_permissions=("runs.cancel",),
            params=(RouteParam(name="run_id", kind="run", field="run_id"),),
        ),
        "answer_hitl": GovernedRoute(
            intent="answer_hitl",
            method="POST",
            path="/v1/hitl/{run_id}/{node_id}/answer",
            required_permissions=("hitl.answer",),
            params=(
                RouteParam(name="run_id", kind="run", field="run_id"),
                RouteParam(name="node_id", kind="node_run", field="node_id"),
            ),
        ),
        "cancel_hitl": GovernedRoute(
            intent="cancel_hitl",
            method="POST",
            path="/v1/hitl/{run_id}/{node_id}/cancel",
            required_permissions=("hitl.cancel",),
            params=(
                RouteParam(name="run_id", kind="run", field="run_id"),
                RouteParam(name="node_id", kind="node_run", field="node_id"),
            ),
        ),
        "start_task": GovernedRoute(
            intent="start_task",
            method="POST",
            path="/v1/tasks",
            required_permissions=("tasks.start",),
        ),
    }
)

#: Intents that mutate canonical state through a governed server seam. Every
#: other declared intent is renderer-local and must not carry a route.
MUTATING_INTENTS: frozenset[str] = frozenset(GOVERNED_ROUTES)

#: Renderer-local intents: no route, no server call.
LOCAL_INTENTS: frozenset[str] = frozenset({"refresh", "navigate", "open_url"})

#: Canonical preconditions a mutating action may declare. Evaluated by the
#: host against the canonical snapshot at render *and* dispatch time; the
#: governed seams enforce their own deeper rules on top.
PRECONDITIONS: frozenset[str] = frozenset({"always", "run_cancellable"})


# --------------------------------------------------------------------------
# Sandbox policy
# --------------------------------------------------------------------------

#: The closed CSP directive vocabulary a component sandbox may declare.
_SANDBOX_DIRECTIVES: tuple[str, ...] = (
    "script_src",
    "style_src",
    "img_src",
    "connect_src",
)

_CSP_DIRECTIVE_NAMES: Mapping[str, str] = {
    "script_src": "script-src",
    "style_src": "style-src",
    "img_src": "img-src",
    "connect_src": "connect-src",
}

#: CSP tokens that are unrestricted access wearing a policy's clothing, and
#: are therefore never acceptable in any declared directive.
_UNSAFE_CSP_TOKENS: frozenset[str] = frozenset(
    {
        "*",
        "'unsafe-inline'",
        "'unsafe-eval'",
        "'unsafe-hashes'",
        "'wasm-unsafe-eval'",
        "'strict-dynamic'",
        "data:",
        "blob:",
        "filesystem:",
    }
)


@dataclass(frozen=True)
class SandboxPolicy:
    """The declared content-security policy of one UI component.

    ``connect_src`` is the component's complete outbound origin authority:
    fetch/connect subresource loads and ``open_url`` targets alike must fall
    inside it. Origins are explicit ``https://host[:port]`` tokens — no
    wildcards, no plaintext HTTP, no scheme-relative shorthands.
    """

    script_src: tuple[str, ...]
    style_src: tuple[str, ...] = ()
    img_src: tuple[str, ...] = ()
    connect_src: tuple[str, ...] = ()

    def to_csp(self) -> str:
        """The header-ready CSP string a hosting client enforces.

        Every declared directive is emitted. An empty directive becomes an
        explicit ``'none'`` deny: omitting it would let the CSP fall through
        to the (absent) ``default-src`` and leave that resource type
        unrestricted, inverting the allowlist the component declared.
        """
        parts: list[str] = []
        for directive in _SANDBOX_DIRECTIVES:
            tokens = getattr(self, directive)
            if tokens:
                parts.append(f"{_CSP_DIRECTIVE_NAMES[directive]} " + " ".join(tokens))
            else:
                parts.append(f"{_CSP_DIRECTIVE_NAMES[directive]} 'none'")
        return "; ".join(parts)

    def allows_outbound_origin(self, target: str) -> bool:
        """Whether an outbound URL (an ``open_url`` target) is policy-allowed.

        Requires an explicit ``https://`` URL (any path — targets navigate,
        they are not origin tokens) whose host/port matches one declared
        ``connect_src`` origin exactly (default port normalized). Anything
        unparsable, plaintext, or undeclared is refused.
        """
        target_origin = _url_origin(target)
        if target_origin is None:
            return False
        return any(_https_origin(token) == target_origin for token in self.connect_src)


def _split_https_url(value: str) -> tuple[SplitResult, int] | None:
    """Split an explicit ``https://`` URL into its parts plus resolved port.

    ``None`` unless the value is a string URL with an https scheme, an
    explicit hostname, and no credentials — the shape every declared origin
    and outbound target must have before anything else is checked. The port
    comes back normalized to 443 when absent.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return parts, 443 if port is None else port


def _https_origin(value: str) -> tuple[str, str, int] | None:
    """Parse an ``https://host[:port]`` origin token; ``None`` if not one.

    Returns the ``(scheme, hostname, port)`` triple with the default port
    normalized, so ``https://host`` equals ``https://host:443``. Origin
    tokens carry no path, query, credentials, or wildcards.
    """
    parsed = _split_https_url(value)
    if parsed is None:
        return None
    parts, port = parsed
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    return ("https", (parts.hostname or "").lower(), port)


def _url_origin(value: str) -> tuple[str, str, int] | None:
    """The origin of an outbound URL target; ``None`` unless explicit https.

    Unlike origin tokens, targets may carry paths and queries — they are
    navigation destinations — but the host/port must still be explicit and
    the scheme must be https.
    """
    parsed = _split_https_url(value)
    if parsed is None:
        return None
    parts, port = parsed
    return ("https", (parts.hostname or "").lower(), port)


def _validate_origin_token(token: str, directive: str) -> None:
    """Reject anything that is not an explicit, non-wildcard https origin."""
    if re.search(r"[\s,;]", token):
        raise CatalogRejected(
            f"sandbox {directive} token {token!r} contains CSP source "
            "delimiters; declare one explicit https://host[:port] origin per token"
        )
    lowered = token.lower()
    if lowered in _UNSAFE_CSP_TOKENS or any(
        lowered.startswith(t) for t in ("data:", "blob:", "filesystem:")
    ):
        raise CatalogRejected(
            f"sandbox {directive} token {token!r} grants unrestricted access; "
            "declare explicit https://host[:port] origins"
        )
    if "*" in token or token.startswith("//") or token.startswith("http://"):
        raise CatalogRejected(
            f"sandbox {directive} token {token!r} is not an explicit https origin"
        )
    if token == "'self'":
        return
    if _https_origin(token) is None:
        raise CatalogRejected(
            f"sandbox {directive} token {token!r} must be 'self' or an "
            "explicit https://host[:port] origin"
        )


def _validate_sandbox_directive(directive: str, tokens: object) -> tuple[str, ...]:
    """Validate one declared CSP directive's token list, failing closed."""
    if not isinstance(tokens, list) or not all(
        isinstance(token, str) and token.strip() for token in tokens
    ):
        raise CatalogRejected(f"sandbox.{directive} must be a list of non-empty strings")
    if len(set(tokens)) != len(tokens):
        raise CatalogRejected(f"sandbox.{directive} repeats a token")
    for token in tokens:
        _validate_origin_token(token, directive)
    return tuple(tokens)


def _validate_sandbox(raw: object) -> SandboxPolicy:
    """Parse and validate one component sandbox block, failing closed."""
    if not isinstance(raw, dict) or not raw:
        raise CatalogRejected("component sandbox must be a non-empty object")
    unknown = sorted(set(raw) - set(_SANDBOX_DIRECTIVES))
    if unknown:
        raise CatalogRejected(f"unknown sandbox directives: {unknown}")
    if "script_src" not in raw:
        raise CatalogRejected(
            "sandbox.script_src is required: a component must declare its "
            "script policy, never inherit a permissive default"
        )
    parsed = {
        directive: ()
        if directive not in raw
        else _validate_sandbox_directive(directive, raw[directive])
        for directive in _SANDBOX_DIRECTIVES
    }
    return SandboxPolicy(
        script_src=parsed["script_src"],
        style_src=parsed["style_src"],
        img_src=parsed["img_src"],
        connect_src=parsed["connect_src"],
    )


# --------------------------------------------------------------------------
# Content scan: injection vectors never pass inspection
# --------------------------------------------------------------------------

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"<script",
        r"<iframe",
        r"<object",
        r"<embed",
        r"javascript:",
        r"vbscript:",
        r"data:text/html",
        r"\beval\s*\(",
        r"\bon[a-z]+\s*=",  # inline event handlers: onclick=, onerror=, ...
        r"\bsrcdoc\b",
    )
)


def _scan_component_text(text: str, what: str) -> None:
    """Reject injection vectors in a component's declared text.

    Components are declarative descriptors, not markup: a renderer consumes
    a component tree, so any script-capable construct in the declared text
    is an injection attempt, not content.
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise CatalogRejected(
                f"component {what} contains a script-injection vector "
                f"({pattern.pattern!r}); UI extensions cannot inject "
                "executable content, only declarative descriptors"
            )


# --------------------------------------------------------------------------
# Manifest model
# --------------------------------------------------------------------------

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_BINDING_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MANIFEST_REQUIRED_KEYS = (
    "manifest_version",
    "catalog_id",
    "name",
    "version",
    "publisher",
    "api_version",
    "components",
)
_MANIFEST_OPTIONAL_KEYS = ("assets",)
_MANIFEST_ALLOWED_KEYS = frozenset({*_MANIFEST_REQUIRED_KEYS, *_MANIFEST_OPTIONAL_KEYS})

_ASSET_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ComponentAsset:
    """One versioned component asset, pinned by digest.

    Paths are relative bundle paths (no traversal, no schemes, no
    absolutes); the digest pins the exact bytes so a rendered surface is
    reproducible from its manifest and its provenance is checkable.
    """

    path: str
    sha256: str
    size: int


def verify_component_asset(asset: ComponentAsset, payload: bytes) -> str:
    """Check asset bytes against the manifest's digest/size claim.

    Returns the verified digest. A mismatch is a tampered bundle: callers
    refuse to serve the asset instead of shipping bytes the manifest never
    claimed.
    """
    digest = sha256_hex(payload)
    if digest != asset.sha256:
        raise CatalogRejected(
            f"asset digest mismatch for {asset.path!r}: manifest declares "
            f"{asset.sha256}, asset carries {digest}"
        )
    if len(payload) != asset.size:
        raise CatalogRejected(
            f"asset size mismatch for {asset.path!r}: manifest declares "
            f"{asset.size}, asset carries {len(payload)}"
        )
    return digest


@dataclass(frozen=True)
class DataBinding:
    """One declared binding to canonical state.

    ``binding`` is the name the component's data payload carries; ``kind``
    selects the canonical object; ``fields`` names the projected fields from
    the :data:`BINDABLE_FIELDS` allowlist.
    """

    binding: str
    kind: CanonicalStateKind
    fields: tuple[str, ...]


@dataclass(frozen=True)
class UiAction:
    """One declared action of a UI component.

    Mutating intents must name exactly their governed route; local intents
    must carry none. ``open_url`` additionally declares its ``target``,
    which must fall inside the sandbox's declared origins.
    """

    action: str
    intent: str
    permissions: tuple[str, ...] = ()
    route: str | None = None
    target: str | None = None
    precondition: str = "always"


@dataclass(frozen=True)
class UiComponentDefinition:
    """One declared UI component: bindings, actions, sandbox, descriptor."""

    component_id: str
    title: str
    sandbox: SandboxPolicy
    bindings: tuple[DataBinding, ...] = ()
    actions: tuple[UiAction, ...] = ()
    #: Principal permissions required to see the component at all. Evaluated
    #: server-side; a component the principal cannot see renders nothing.
    required_permissions: tuple[str, ...] = ()
    description: str = ""
    #: Declarative view descriptor (an A2UI-style component-tree document or
    #: an equivalent template reference). Scanned for injection vectors.
    template: str = ""

    def action(self, name: str) -> UiAction | None:
        """The declared action with ``name``, if any."""
        for declared in self.actions:
            if declared.action == name:
                return declared
        return None

    def binding_names(self) -> frozenset[str]:
        """The declared binding names — the component's client-state boundary."""
        return frozenset(declared.binding for declared in self.bindings)


@dataclass(frozen=True)
class UiComponentManifest:
    """The immutable snapshot of one inspected UI catalog manifest.

    ``raw`` is the exact bytes the governed install authorized and
    ``source_sha256`` anchors them — the digest every rendered component's
    provenance cites, so what a surface displays is checkable against what
    was installed.
    """

    manifest_version: int
    catalog_id: str
    name: str
    version: str
    publisher: str
    api_version: str
    components: tuple[UiComponentDefinition, ...]
    assets: tuple[ComponentAsset, ...] = ()
    source_sha256: str = ""
    raw: bytes = field(default=b"", repr=False, compare=False)

    def component(self, component_id: str) -> UiComponentDefinition | None:
        """The declared component with ``component_id``, if any."""
        for declared in self.components:
            if declared.component_id == component_id:
                return declared
        return None


def assert_ui_snapshot_intact(manifest: UiComponentManifest) -> None:
    """Raise unless the snapshot's fields are exactly what its bytes parse to.

    Every projection and dispatch re-verifies the snapshot, so a corrupted
    or swapped manifest fails loudly instead of rendering something nobody
    authorized. Hashing ``raw`` alone would let a ``dataclasses.replace()``
    carry substituted fields under the original anchor, so the anchored
    bytes are reparsed and the complete snapshot compared field for field.
    """
    if sha256_hex(manifest.raw) != manifest.source_sha256:
        raise CatalogRejected(
            f"UI manifest snapshot integrity failure for {manifest.catalog_id!r}: "
            "bytes no longer match the inspected digest"
        )
    reparsed = inspect_ui_manifest(manifest.raw)
    if reparsed != manifest:
        raise CatalogRejected(
            f"UI manifest snapshot integrity failure for {manifest.catalog_id!r}: "
            "parsed fields differ from the anchored manifest bytes"
        )


# --------------------------------------------------------------------------
# Provenance and rendered output
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentProvenance:
    """Where a rendered component came from, stated on every render.

    Inspectable in rendered extension metadata: the catalog (extension) id,
    the component id, the semantic version, the publisher, and the SHA-256
    of the exact manifest bytes projected.
    """

    catalog_id: str
    component_id: str
    version: str
    publisher: str
    manifest_sha256: str


@dataclass(frozen=True)
class ActionAvailability:
    """One action's server-evaluated availability, with the reason."""

    action: str
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class RenderedComponent:
    """One component's projection: canonical data, availability, provenance.

    ``data`` carries exactly the declared bindings' declared fields from the
    host-supplied canonical snapshot — nothing more. When the component is
    not visible to the principal, ``data`` is empty: visibility withholds
    the projection, not just the chrome.
    """

    component_id: str
    visible: bool
    data: Mapping[str, Mapping[str, Any]]
    actions: tuple[ActionAvailability, ...]
    sandbox_csp: str
    provenance: ComponentProvenance


@dataclass(frozen=True)
class GovernedActionCall:
    """A dispatched action resolved to its governed server seam.

    The host executes this call against the canonical API with the
    principal's own credentials; the seam's own authorization still applies.
    ``provenance`` rides along so the audit trail can say which installed
    component version asked for the mutation.
    """

    component_id: str
    action: str
    intent: str
    method: str
    path: str
    arguments: Mapping[str, Any]
    permissions_required: tuple[str, ...]
    principal: str
    provenance: ComponentProvenance


# --------------------------------------------------------------------------
# Manifest inspection (pure byte handling, never imports anything)
# --------------------------------------------------------------------------


def _reject(detail: str) -> CatalogRejected:
    return CatalogRejected(f"invalid UI component manifest: {detail}")


def _require_token(value: object, what: str) -> str:
    """Validate one dotted lowercase identifier token."""
    if not isinstance(value, str) or _ID_RE.match(value) is None:
        raise _reject(f"{what} must be a lowercase dotted identifier, got {value!r}")
    return value


def _require_semver(value: object, what: str) -> str:
    if not isinstance(value, str) or SEMVER_RE.match(value) is None:
        raise _reject(f"{what} must be semver X.Y.Z, got {value!r}")
    return value


def _require_str(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _reject(f"{what} must be a non-empty string")
    return value


def _parse_permission_tokens(raw: object, what: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise _reject(f"{what} must be a list of strings")
    seen: set[str] = set()
    for token in raw:
        if _ID_RE.match(token) is None:
            raise _reject(f"malformed permission token in {what}: {token!r}")
        if token in seen:
            raise _reject(f"{what} repeats permission {token!r}")
        seen.add(token)
    return tuple(raw)


def _validate_asset_path(path: object) -> str:
    if not isinstance(path, str) or not path.strip():
        raise _reject("asset path must be a non-empty string")
    if path.startswith(("/", "\\")) or ".." in path or ":" in path or "\\" in path:
        raise _reject(
            f"asset path {path!r} must be a relative bundle path without "
            "traversal, schemes, or backslashes"
        )
    return path


def _parse_asset(raw: object) -> ComponentAsset:
    if not isinstance(raw, dict) or set(raw) != {"path", "sha256", "size"}:
        raise _reject("each asset must be an object with exactly path, sha256, size")
    path = _validate_asset_path(raw["path"])
    digest = raw["sha256"]
    if not isinstance(digest, str) or _ASSET_SHA256_RE.fullmatch(digest) is None:
        raise _reject(f"asset {path!r} sha256 must be a lowercase 64-hex digest")
    size = raw["size"]
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise _reject(f"asset {path!r} size must be a positive integer")
    return ComponentAsset(path=path, sha256=digest, size=size)


def _validate_binding_fields(
    fields: object, kind: str, name: str, component_id: str
) -> tuple[str, ...]:
    """Validate one binding's field list against the projection allowlist."""
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(declared, str) for declared in fields)
    ):
        raise _reject(
            f"component {component_id!r}: binding {name!r} fields must be a "
            "non-empty list of strings"
        )
    allowed = BINDABLE_FIELDS[kind]
    for declared_field in fields:
        if declared_field not in allowed:
            raise _reject(
                f"component {component_id!r}: binding {name!r} field "
                f"{declared_field!r} is not a projectable {kind} field; "
                f"allowed: {list(allowed)}"
            )
    if len(set(fields)) != len(fields):
        raise _reject(f"component {component_id!r}: binding {name!r} repeats a field")
    return tuple(fields)


def _parse_binding(raw: object, component_id: str, seen: set[str]) -> DataBinding:
    if not isinstance(raw, dict) or set(raw) != {"binding", "kind", "fields"}:
        raise _reject(
            f"component {component_id!r}: each binding must be an object with "
            "exactly binding, kind, fields"
        )
    name = raw["binding"]
    if not isinstance(name, str) or _BINDING_NAME_RE.match(name) is None:
        raise _reject(f"component {component_id!r}: malformed binding name {name!r}")
    if name in seen:
        raise _reject(f"component {component_id!r}: duplicate binding {name!r}")
    seen.add(name)
    kind = raw["kind"]
    if not isinstance(kind, str) or kind not in SUPPORTED_STATE_KINDS:
        raise _reject(
            f"component {component_id!r}: binding {name!r} references "
            f"{kind!r}, which is not canonical state; bindings may only "
            f"reference {sorted(SUPPORTED_STATE_KINDS)}"
        )
    fields = _validate_binding_fields(raw["fields"], kind, name, component_id)
    return DataBinding(binding=name, kind=kind, fields=fields)


def _route_string(route: GovernedRoute) -> str:
    return f"{route.method} {route.path}"


def _parse_mutating_action(
    raw: Mapping[str, object],
    name: str,
    intent: str,
    permissions: tuple[str, ...],
    precondition: str,
    component_id: str,
) -> UiAction:
    """Validate one mutating action: governed seam exactly, authority canonical.

    The permission set protecting a governed mutation is fixed by the route,
    not chosen by the catalog: the declaration must equal the seam's
    ``required_permissions`` exactly, so a low-authority token can never be
    swapped in to unlock a mutation the operator did not bind to it.
    """
    governed = GOVERNED_ROUTES[intent]
    if set(permissions) != set(governed.required_permissions):
        raise _reject(
            f"component {component_id!r}: mutating action {name!r} must declare "
            f"exactly the canonical permissions for {intent!r} "
            f"({list(governed.required_permissions)}), got {list(permissions)}"
        )
    route = raw.get("route")
    if not isinstance(route, str) or route != _route_string(governed):
        raise _reject(
            f"component {component_id!r}: mutating action {name!r} must "
            f"target its governed seam exactly ({_route_string(governed)}), "
            f"got {route!r}; UI mutations can only call canonical server APIs"
        )
    if raw.get("target") is not None:
        raise _reject(
            f"component {component_id!r}: mutating action {name!r} cannot declare a target"
        )
    return UiAction(
        action=name,
        intent=intent,
        permissions=permissions,
        route=route,
        precondition=precondition,
    )


def _parse_local_action(
    raw: Mapping[str, object],
    name: str,
    intent: str,
    permissions: tuple[str, ...],
    precondition: str,
    component_id: str,
    sandbox: SandboxPolicy,
) -> UiAction:
    """Validate one renderer-local action: no route, no server authority."""
    if raw.get("route") is not None:
        raise _reject(
            f"component {component_id!r}: local action {name!r} cannot declare "
            "a route; renderer-local intents never call the server"
        )
    if permissions:
        raise _reject(
            f"component {component_id!r}: local action {name!r} cannot require "
            "permissions; renderer-local intents exercise no server authority"
        )
    target = raw.get("target")
    if intent == "open_url":
        if not isinstance(target, str) or not target.strip():
            raise _reject(
                f"component {component_id!r}: open_url action {name!r} must declare its target URL"
            )
        _scan_component_text(target, f"action {name!r} target")
        if not sandbox.allows_outbound_origin(target):
            raise _reject(
                f"component {component_id!r}: open_url action {name!r} target "
                f"{target!r} is outside the declared sandbox origins; extension "
                "UI cannot reach the network outside declared policy"
            )
    elif target is not None:
        raise _reject(f"component {component_id!r}: action {name!r} cannot declare a target")
    return UiAction(
        action=name,
        intent=intent,
        permissions=(),
        target=target if isinstance(target, str) else None,
        precondition=precondition,
    )


def _validated_action_fields(
    raw: Mapping[str, object],
    component_id: str,
    seen: set[str],
) -> tuple[str, str, tuple[str, ...], str]:
    """Validate an action declaration's identity fields and return them."""
    for required in ("action", "intent"):
        if required not in raw:
            raise _reject(f"component {component_id!r}: action missing {required!r}")
    name = raw["action"]
    if not isinstance(name, str) or _BINDING_NAME_RE.match(name) is None:
        raise _reject(f"component {component_id!r}: malformed action name {name!r}")
    if name in seen:
        raise _reject(f"component {component_id!r}: duplicate action {name!r}")
    seen.add(name)

    intent = raw["intent"]
    if not isinstance(intent, str) or (
        intent not in MUTATING_INTENTS and intent not in LOCAL_INTENTS
    ):
        raise _reject(
            f"component {component_id!r}: action {name!r} declares unknown "
            f"intent {intent!r}; the governed vocabulary is "
            f"{sorted(MUTATING_INTENTS | LOCAL_INTENTS)}"
        )

    permissions = _parse_permission_tokens(
        raw.get("permissions", []), f"action {name!r} permissions"
    )
    precondition = raw.get("precondition", "always")
    if not isinstance(precondition, str) or precondition not in PRECONDITIONS:
        raise _reject(
            f"component {component_id!r}: action {name!r} declares unknown "
            f"precondition {precondition!r}; known: {sorted(PRECONDITIONS)}"
        )
    return name, intent, permissions, precondition


def _parse_action(
    raw: object,
    component_id: str,
    sandbox: SandboxPolicy,
    seen: set[str],
) -> UiAction:
    if not isinstance(raw, dict):
        raise _reject(f"component {component_id!r}: each action must be an object")
    allowed = {"action", "intent", "permissions", "route", "target", "precondition"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise _reject(f"component {component_id!r}: unknown action keys: {unknown}")
    name, intent, permissions, precondition = _validated_action_fields(raw, component_id, seen)

    if intent in MUTATING_INTENTS:
        return _parse_mutating_action(raw, name, intent, permissions, precondition, component_id)
    return _parse_local_action(raw, name, intent, permissions, precondition, component_id, sandbox)


def _parse_component_text(raw: Mapping[str, object], component_id: str) -> tuple[str, str, str]:
    """Extract and injection-scan a component's title/description/template."""
    title = _require_str(raw["title"], f"component {component_id!r} title")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise _reject(f"component {component_id!r}: description must be a string")
    template = raw.get("template", "")
    if not isinstance(template, str):
        raise _reject(f"component {component_id!r}: template must be a string")
    _scan_component_text(title, f"{component_id!r} title")
    _scan_component_text(description, f"{component_id!r} description")
    _scan_component_text(template, f"{component_id!r} template")
    return title, description, template


def _parse_component_members(
    raw: Mapping[str, object],
    component_id: str,
    sandbox: SandboxPolicy,
) -> tuple[tuple[DataBinding, ...], tuple[UiAction, ...], tuple[str, ...]]:
    """Parse a component's bindings, actions, and required permissions."""
    bindings_raw = raw.get("bindings", [])
    if not isinstance(bindings_raw, list):
        raise _reject(f"component {component_id!r}: bindings must be a list")
    seen_bindings: set[str] = set()
    bindings = tuple(_parse_binding(item, component_id, seen_bindings) for item in bindings_raw)

    actions_raw = raw.get("actions", [])
    if not isinstance(actions_raw, list):
        raise _reject(f"component {component_id!r}: actions must be a list")
    seen_actions: set[str] = set()
    actions = tuple(
        _parse_action(item, component_id, sandbox, seen_actions) for item in actions_raw
    )

    required_permissions = _parse_permission_tokens(
        raw.get("required_permissions", []),
        f"component {component_id!r} required_permissions",
    )
    return bindings, actions, required_permissions


def _parse_component(raw: object, seen_components: set[str]) -> UiComponentDefinition:
    if not isinstance(raw, dict):
        raise _reject("each component must be an object")
    allowed = {
        "component_id",
        "title",
        "description",
        "bindings",
        "actions",
        "required_permissions",
        "sandbox",
        "template",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise _reject(f"unknown component keys: {unknown}")
    missing = [key for key in ("component_id", "title", "sandbox") if key not in raw]
    if missing:
        raise _reject(f"component missing keys: {missing}")

    component_id = _require_token(raw["component_id"], "component_id")
    if component_id in seen_components:
        raise _reject(f"duplicate component id: {component_id!r}")
    seen_components.add(component_id)

    title, description, template = _parse_component_text(raw, component_id)
    sandbox = _validate_sandbox(raw["sandbox"])
    bindings, actions, required_permissions = _parse_component_members(raw, component_id, sandbox)

    return UiComponentDefinition(
        component_id=component_id,
        title=title,
        sandbox=sandbox,
        bindings=bindings,
        actions=actions,
        required_permissions=required_permissions,
        description=description,
        template=template,
    )


def _parse_manifest_envelope(document: Mapping[str, object]) -> tuple[str, str, str, str, str]:
    """Validate envelope keys/version and identity fields; return them."""
    unknown = sorted(set(document) - _MANIFEST_ALLOWED_KEYS)
    if unknown:
        raise _reject(f"unknown manifest keys: {unknown}")
    missing = [key for key in _MANIFEST_REQUIRED_KEYS if key not in document]
    if missing:
        raise _reject(f"missing manifest keys: {missing}")
    if document["manifest_version"] != UI_MANIFEST_VERSION:
        raise _reject(f"unsupported manifest_version: {document['manifest_version']!r}")

    catalog_id = _require_token(document["catalog_id"], "catalog_id")
    name = _require_str(document["name"], "name")
    publisher = document["publisher"]
    if not isinstance(publisher, str) or not publisher.strip():
        raise _reject("publisher must be a non-empty string")
    version = _require_semver(document["version"], "version")
    api_version = _require_semver(document["api_version"], "api_version")
    return catalog_id, name, publisher, version, api_version


def _parse_components_and_assets(
    document: Mapping[str, object],
) -> tuple[tuple[UiComponentDefinition, ...], tuple[ComponentAsset, ...]]:
    """Parse the components and versioned assets of an envelope."""
    components_raw = document["components"]
    if not isinstance(components_raw, list) or not components_raw:
        raise _reject("components must be a non-empty list")
    seen_components: set[str] = set()
    components = tuple(_parse_component(item, seen_components) for item in components_raw)

    assets_raw = document.get("assets", [])
    if not isinstance(assets_raw, list):
        raise _reject("assets must be a list")
    assets = tuple(_parse_asset(item) for item in assets_raw)
    paths = [asset.path for asset in assets]
    if len(set(paths)) != len(paths):
        raise _reject("assets repeat a path")
    return components, assets


def inspect_ui_manifest(raw: bytes) -> UiComponentManifest:
    """Parse and validate UI catalog manifest bytes into an immutable snapshot.

    Fails closed on malformed JSON, unknown envelope versions or keys,
    malformed identifiers, non-projectable bindings, ungoverned action
    routes, injection vectors, and unsafe sandbox declarations. Never
    imports anything and never touches the network: a manifest is data.
    """
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _reject(f"not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise _reject("top-level document must be an object")

    catalog_id, name, publisher, version, api_version = _parse_manifest_envelope(document)
    components, assets = _parse_components_and_assets(document)

    return UiComponentManifest(
        manifest_version=UI_MANIFEST_VERSION,
        catalog_id=catalog_id,
        name=name,
        version=version,
        publisher=publisher,
        api_version=api_version,
        components=components,
        assets=assets,
        source_sha256=sha256_hex(raw),
        raw=raw,
    )


# --------------------------------------------------------------------------
# Projection service (the host-side governed render/dispatch surface)
# --------------------------------------------------------------------------

#: The host-supplied check that an extension is active in a scope — backed by
#: the governed install store in production. A catalog whose extension is not
#: active renders nothing and dispatches nothing.
ExtensionActiveCheck = Callable[[ExtensionScope, str], Awaitable[bool]]

#: Every canonical field name, across kinds: the reserved vocabulary a
#: client's action arguments may never carry.
_RESERVED_CLIENT_KEYS: frozenset[str] = frozenset(
    name for fields in BINDABLE_FIELDS.values() for name in fields
)


def _field_value(source: Any, declared_field: str) -> Any:
    """Read one canonical field from a model object or mapping snapshot."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        value: Any = source.get(declared_field)
    else:
        value = getattr(source, declared_field, None)
    if isinstance(value, Enum):
        return value.value
    return value


def _total_state(
    canonical_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """A total mapping over the supported kinds; unprojected kinds read None."""
    total: dict[str, Any] = dict.fromkeys(SUPPORTED_STATE_KINDS)
    if canonical_state is not None:
        total.update(canonical_state)
    return total


def _is_visible(component: UiComponentDefinition, principal_permissions: frozenset[str]) -> bool:
    return set(component.required_permissions) <= principal_permissions


def _provenance_of(
    manifest: UiComponentManifest, declared: UiComponentDefinition
) -> ComponentProvenance:
    return ComponentProvenance(
        catalog_id=manifest.catalog_id,
        component_id=declared.component_id,
        version=manifest.version,
        publisher=manifest.publisher,
        manifest_sha256=manifest.source_sha256,
    )


class UiProjectionService:
    """Governed projection of canonical state for installed UI extensions.

    One service holds the catalogs declared by active installs — keyed by
    ``(scope, extension_id)`` so the same extension active in two scopes can
    carry a different installed manifest and grant set per scope — and
    answers two questions, backed by the *same* availability evaluation:

    - ``render`` — what a client may display (pure projection of the
      host-supplied canonical snapshot, with per-action availability and
      provenance attached);
    - ``dispatch`` — what the server will honor (re-evaluates every
      availability rule server-side, then resolves the governed seam).

    The service never reads a store, opens a session, or performs I/O: the
    host supplies canonical snapshots and the extension-active check.
    """

    def __init__(
        self,
        catalogs: Mapping[tuple[ExtensionScope, str], UiComponentManifest],
        *,
        extension_active: ExtensionActiveCheck,
        extension_permissions: Mapping[tuple[ExtensionScope, str], frozenset[str]] | None = None,
    ) -> None:
        for (_scope, extension_id), manifest in catalogs.items():
            if manifest.catalog_id != extension_id:
                raise ValueError(
                    f"catalog {manifest.catalog_id!r} registered under "
                    f"{extension_id!r}: a catalog is addressable only by the "
                    "extension id that shipped it"
                )
        for manifest in catalogs.values():
            assert_ui_snapshot_intact(manifest)
        self._catalogs: dict[tuple[ExtensionScope, str], UiComponentManifest] = dict(catalogs)
        self._extension_active = extension_active
        self._extension_permissions = (
            dict(extension_permissions) if extension_permissions is not None else {}
        )

    def register(self, manifest: UiComponentManifest, *, scope: ExtensionScope) -> None:
        """Register (or re-register) a catalog under (scope, extension id)."""
        assert_ui_snapshot_intact(manifest)
        self._catalogs[(scope, manifest.catalog_id)] = manifest

    # -- reads ------------------------------------------------------------

    def _require_catalog(self, scope: ExtensionScope, extension_id: str) -> UiComponentManifest:
        manifest = self._catalogs.get((scope, extension_id))
        if manifest is None:
            raise UnknownCatalog(f"no UI component catalog for extension {extension_id!r}")
        assert_ui_snapshot_intact(manifest)
        return manifest

    # -- render -----------------------------------------------------------

    async def render(
        self,
        *,
        scope: ExtensionScope,
        extension_id: str,
        principal_permissions: frozenset[str],
        canonical_state: Mapping[str, Any] | None = None,
    ) -> tuple[RenderedComponent, ...]:
        """Project every component of one extension's catalog for a principal.

        Pure over the supplied snapshot: the same inputs always render the
        same output, so a client reload re-projects from a fresh canonical
        read without altering anything.
        """
        manifest = self._require_catalog(scope, extension_id)
        active = await self._extension_active(scope, extension_id)
        state = _total_state(canonical_state)
        extension_grant = self._extension_permissions.get((scope, extension_id), frozenset())
        return tuple(
            self._render_component(
                manifest,
                declared,
                active=active,
                extension_grant=extension_grant,
                principal_permissions=principal_permissions,
                state=state,
            )
            for declared in manifest.components
        )

    async def render_component(
        self,
        *,
        scope: ExtensionScope,
        extension_id: str,
        component_id: str,
        principal_permissions: frozenset[str],
        canonical_state: Mapping[str, Any] | None = None,
    ) -> RenderedComponent:
        """Project one component; :class:`UnknownComponent` if undeclared."""
        manifest = self._require_catalog(scope, extension_id)
        declared = manifest.component(component_id)
        if declared is None:
            raise UnknownComponent(
                f"catalog {manifest.catalog_id!r} declares no component {component_id!r}"
            )
        active = await self._extension_active(scope, extension_id)
        state = _total_state(canonical_state)
        extension_grant = self._extension_permissions.get((scope, extension_id), frozenset())
        return self._render_component(
            manifest,
            declared,
            active=active,
            extension_grant=extension_grant,
            principal_permissions=principal_permissions,
            state=state,
        )

    def _render_component(
        self,
        manifest: UiComponentManifest,
        declared: UiComponentDefinition,
        *,
        active: bool,
        extension_grant: frozenset[str],
        principal_permissions: frozenset[str],
        state: Mapping[str, Any],
    ) -> RenderedComponent:
        visible = active and _is_visible(declared, principal_permissions)
        data: dict[str, dict[str, Any]] = {}
        if visible:
            for binding in declared.bindings:
                source = state.get(binding.kind)
                data[binding.binding] = {
                    name: _field_value(source, name) for name in binding.fields
                }
        provenance = _provenance_of(manifest, declared)
        return RenderedComponent(
            component_id=declared.component_id,
            visible=visible,
            data=data,
            actions=tuple(
                self._availability(
                    action,
                    active=active,
                    extension_grant=extension_grant,
                    principal_permissions=principal_permissions,
                    state=state,
                )
                for action in declared.actions
            ),
            sandbox_csp=declared.sandbox.to_csp(),
            provenance=provenance,
        )

    # -- availability -------------------------------------------------------

    def _availability(
        self,
        action: UiAction,
        *,
        active: bool,
        extension_grant: frozenset[str],
        principal_permissions: frozenset[str],
        state: Mapping[str, Any],
    ) -> ActionAvailability:
        """The one availability evaluation, shared by render and dispatch."""
        if not active:
            return ActionAvailability(action.action, False, "extension is not active in this scope")
        if action.intent not in MUTATING_INTENTS:
            return ActionAvailability(action.action, True)
        missing_grant = sorted(set(action.permissions) - extension_grant)
        if missing_grant:
            return ActionAvailability(
                action.action,
                False,
                "extension grant does not cover: " + ", ".join(missing_grant),
            )
        missing_principal = sorted(set(action.permissions) - principal_permissions)
        if missing_principal:
            return ActionAvailability(
                action.action,
                False,
                "principal lacks permission: " + ", ".join(missing_principal),
            )
        if action.precondition == "run_cancellable":
            status = _field_value(state.get("run"), "status")
            if not isinstance(status, str) or status not in _CANCELLABLE_RUN_STATUSES:
                return ActionAvailability(
                    action.action,
                    False,
                    f"run status {status!r} is not cancellable",
                )
        governed = GOVERNED_ROUTES[action.intent]
        if governed.resolved_path(state) is None:
            return ActionAvailability(
                action.action,
                False,
                "canonical target is not projected in this scope",
            )
        return ActionAvailability(action.action, True)

    # -- dispatch -----------------------------------------------------------

    async def dispatch(
        self,
        *,
        scope: ExtensionScope,
        extension_id: str,
        component_id: str,
        action: str,
        principal: str,
        principal_permissions: frozenset[str],
        arguments: Mapping[str, Any] | None = None,
        canonical_state: Mapping[str, Any] | None = None,
    ) -> GovernedActionCall:
        """Enforce availability server-side and resolve the governed call.

        This is the enforcement point the rendered metadata only previews:
        every rule is re-evaluated here, at invocation time, from the
        host-supplied canonical snapshot. The returned
        :class:`GovernedActionCall` names the canonical seam; the host
        executes it with the principal's credentials and the seam's own
        authorization still applies. Renderer-local actions have no server
        seam and never dispatch.
        """
        if not principal.strip():
            raise ValueError("principal is required: every dispatch is attributed")
        manifest = self._require_catalog(scope, extension_id)
        declared = manifest.component(component_id)
        if declared is None:
            raise UnknownComponent(
                f"catalog {manifest.catalog_id!r} declares no component {component_id!r}"
            )
        if not _is_visible(declared, principal_permissions):
            missing = sorted(set(declared.required_permissions) - principal_permissions)
            raise ActionUnavailable(
                f"component {component_id!r} is not visible to this principal: "
                "missing permission: " + ", ".join(missing)
            )
        declared_action = declared.action(action)
        if declared_action is None:
            raise UnknownAction(f"component {component_id!r} declares no action {action!r}")
        if declared_action.intent not in MUTATING_INTENTS:
            raise ActionUnavailable(
                f"action {action!r} is renderer-local ({declared_action.intent}); "
                "local actions dispatch nothing"
            )

        client_arguments = dict(arguments) if arguments is not None else {}
        reserved = _RESERVED_CLIENT_KEYS | declared.binding_names()
        smuggled = sorted(set(client_arguments) & reserved)
        if smuggled:
            raise ClientStateRejected(
                f"action arguments carry canonical or binding state ({smuggled}); "
                "canonical state is read from the host's own snapshot and "
                "cannot be supplied by the client"
            )

        active = await self._extension_active(scope, extension_id)
        state = _total_state(canonical_state)
        availability = self._availability(
            declared_action,
            active=active,
            extension_grant=self._extension_permissions.get((scope, extension_id), frozenset()),
            principal_permissions=principal_permissions,
            state=state,
        )
        if not availability.available:
            raise ActionUnavailable(
                f"action {action!r} on {component_id!r} is unavailable: {availability.reason}"
            )

        governed = GOVERNED_ROUTES[declared_action.intent]
        resolved = governed.resolved_path(state)
        if resolved is None:  # pragma: no cover - availability already checked
            raise ActionUnavailable(f"action {action!r} cannot resolve its canonical target")
        return GovernedActionCall(
            component_id=declared.component_id,
            action=declared_action.action,
            intent=declared_action.intent,
            method=governed.method,
            path=resolved,
            arguments=client_arguments,
            permissions_required=governed.required_permissions,
            principal=principal,
            provenance=_provenance_of(manifest, declared),
        )
