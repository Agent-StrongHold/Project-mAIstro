"""The host lifecycle simulation: discover → validate → grant → load → invoke
→ release (#974).

This is the local stand-in for a production host, built strictly over the
public contracts: the six documented stages, in the documented order, with
the documented guarantee — **data about the extension is accepted before the
extension's code executes at all**. The class shape enforces the order: a
`LoadedExtension` cannot exist until a manifest validated, grants resolved,
and only then did the entrypoint module get imported (the first code that
runs).

Simulation boundaries, stated so no report can overclaim:

- the harness is not a sandbox and runs no product: no canonical
  `Goal -> Graph -> Run -> NodeRun -> Attempt` execution is created, no org
  policy is evaluated, no network/filesystem/secrets authority is exercised;
- cancellation is deterministic and host-side: once cancellation is
  requested, the host refuses to call the handler again (it never times
  anything with a wall clock);
- the entrypoint protocol exercised is the documented data-only shape (the
  reference extension's `PLUGIN` object plus a named handler). The typed
  context/hook signatures land with the M9-A2 lifecycle contracts (#950);
  until then handlers are invoked zero-argument unless their signature
  declares a first parameter, in which case the built context is passed.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from maistro_ext_harness.context import ExtensionContext, build_context
from maistro_ext_harness.contract import ContractError
from maistro_ext_harness.fixtures import (
    FixtureSet,
    InvocationFixture,
    reference_fixtures,
)
from maistro_ext_harness.grants import Grant, GrantPolicy, resolve_grants
from maistro_ext_harness.manifest import ExtensionManifest, load_manifest_file

__all__ = [
    "DiscoveredExtension",
    "EntrypointMissing",
    "ExtensionHost",
    "HandlerMissing",
    "HandlerRaised",
    "HostError",
    "InvocationCancelled",
    "LoadedExtension",
    "SubjectNotDiscovered",
]

_MANIFEST_NAME = "extension.json"


class HostError(ContractError):
    """Base class for lifecycle failures the harness raises."""


class SubjectNotDiscovered(HostError):
    """The given path holds no extension: no manifest, or an unreadable one."""


class EntrypointMissing(HostError):
    """The manifest validated but its entrypoint module or object is absent."""


class HandlerMissing(HostError):
    """The entrypoint object names a handler the module does not provide."""


class HandlerRaised(HostError):
    """The handler raised; the host contained it (original as `__cause__`)."""


class InvocationCancelled(HostError):
    """Cancellation was requested before the call; the handler never ran."""


@dataclass(frozen=True)
class DiscoveredExtension:
    """A found extension: paths only. Discovery runs no code."""

    root: Path
    manifest_path: Path


@dataclass
class LoadedExtension:
    """A validated, granted, imported extension — the first code has run."""

    manifest: ExtensionManifest
    grant: Grant
    module: ModuleType
    plugin_object: object
    context: ExtensionContext
    fixtures: FixtureSet
    _cancelled: bool = field(default=False)

    def request_cancel(self) -> None:
        """Host-side cancellation: deterministic, before the next call.

        The context the next invocation would see carries
        `cancel_requested=True`, so a cooperating handler can observe the
        cancellation; the host itself refuses to invoke anything further.
        """
        self._cancelled = True
        cancelled = InvocationFixture(
            invocation_id=self.fixtures.invocation.invocation_id,
            node_ref=self.fixtures.invocation.node_ref,
            cancel_requested=True,
        )
        self.fixtures = FixtureSet(
            identity=self.fixtures.identity,
            workspace=self.fixtures.workspace,
            invocation=cancelled,
        )
        self.context = build_context(
            self.grant,
            identity=self.fixtures.identity,
            workspace=self.fixtures.workspace,
            invocation=cancelled,
        )

    @property
    def cancelled(self) -> bool:
        return self._cancelled


def _discover(root: Path) -> DiscoveredExtension:
    root = root.resolve()
    if not root.is_dir():
        raise SubjectNotDiscovered(f"{root} is not a directory")
    manifest_path = root / _MANIFEST_NAME
    if not manifest_path.is_file():
        raise SubjectNotDiscovered(f"{root} holds no {_MANIFEST_NAME}")
    return DiscoveredExtension(root=root, manifest_path=manifest_path)


def _search_roots(discovered: DiscoveredExtension) -> tuple[Path, ...]:
    """Where the extension's package may live: `src/` layout or flat."""
    src = discovered.root / "src"
    if src.is_dir():
        return (src, discovered.root)
    return (discovered.root,)


def _resolve_handler(loaded: LoadedExtension) -> Any:
    """Resolve the declared handler over the documented data-only protocol.

    The entrypoint object is plain data: a mapping naming what a host may
    call (`handler`), or itself callable. A mapping's handler resolves via
    the module's `HANDLERS` table first, then as a module attribute.
    """
    module = loaded.module
    obj = loaded.plugin_object
    handler_name: str | None = None
    if isinstance(obj, dict):
        named = obj.get("handler")
        if not isinstance(named, str):
            raise HandlerMissing(
                f"entrypoint object for {loaded.manifest.id!r} is a mapping without "
                "a string 'handler' naming what a host may call"
            )
        handler_name = named
        handlers_table = getattr(module, "HANDLERS", None)
        if isinstance(handlers_table, dict) and handler_name in handlers_table:
            return handlers_table[handler_name]
        candidate = getattr(module, handler_name, None)
    else:
        candidate = obj
    if candidate is None:
        raise HandlerMissing(
            f"handler {handler_name!r} declared by {loaded.manifest.id!r} does not "
            f"resolve on module {module.__name__!r}"
        )
    if not callable(candidate):
        raise HandlerMissing(f"handler {handler_name!r} of {loaded.manifest.id!r} is not callable")
    return candidate


def _call(handler: Any, context: ExtensionContext) -> Any:
    """Invoke a handler: zero-argument when the signature allows it, else
    with the context as the single positional argument.

    The bridge exists because the typed context signature is the pending
    M9-A2 contract; today's documented reference handlers take no arguments.
    A handler whose signature accepts a first parameter gets the context —
    the same object a production host would pass.
    """
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return handler()
    positional = [
        p
        for p in signature.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    required = [
        p
        for p in positional
        if p.default is inspect.Parameter.empty and p.kind != inspect.Parameter.VAR_POSITIONAL
    ]
    if required:
        return handler(context)
    return handler()


class ExtensionHost:
    """The six-stage lifecycle, each stage a named method.

    A subject moves `discover → validate → load` through this host; the type
    progression (`DiscoveredExtension` then `LoadedExtension`) makes "no
    code before validation" a property of the API rather than of discipline.
    """

    def __init__(self, policy: GrantPolicy | None = None) -> None:
        self._policy = policy

    def discover(self, root: Path) -> DiscoveredExtension:
        """Stage 1 — find the manifest. Path and metadata reading only."""
        return _discover(root)

    def validate(self, discovered: DiscoveredExtension) -> ExtensionManifest:
        """Stage 2 — validate the manifest. Still no code."""
        return load_manifest_file(discovered.manifest_path)

    def grants_for(self, manifest: ExtensionManifest) -> Grant:
        """Stage 3 — resolve grants from declarations (optionally narrowed)."""
        return resolve_grants(manifest, self._policy)

    def load(
        self,
        discovered: DiscoveredExtension,
        manifest: ExtensionManifest,
        grant: Grant,
        *,
        fixtures: FixtureSet | None = None,
    ) -> LoadedExtension:
        """Stage 4 — import the entrypoint. The first extension code runs here."""
        module = self._import_entrypoint(discovered, manifest)
        obj = getattr(module, manifest.entrypoint.object, None)
        if obj is None:
            raise EntrypointMissing(
                f"entrypoint object {manifest.entrypoint.object!r} not found in module "
                f"{manifest.entrypoint.module!r} of {manifest.id!r}"
            )
        fx = fixtures or reference_fixtures()
        context = build_context(
            grant, identity=fx.identity, workspace=fx.workspace, invocation=fx.invocation
        )
        return LoadedExtension(
            manifest=manifest,
            grant=grant,
            module=module,
            plugin_object=obj,
            context=context,
            fixtures=fx,
        )

    def _import_entrypoint(
        self, discovered: DiscoveredExtension, manifest: ExtensionManifest
    ) -> ModuleType:
        dotted = manifest.entrypoint.module
        roots = _search_roots(discovered)
        for candidate_root in roots:
            top = dotted.split(".")[0]
            if (candidate_root / top).is_dir():
                return self._import_with_path(candidate_root, dotted)
        raise EntrypointMissing(
            f"entrypoint module {dotted!r} of {manifest.id!r} does not exist under "
            f"{discovered.root} (looked for a package in src/ and at the root)"
        )

    def _import_with_path(self, package_root: Path, dotted: str) -> ModuleType:
        """Import `dotted` with the extension's package root on sys.path.

        This is the host importing extension code — the one legitimate place
        the extension's checkout touches the interpreter's path. The root is
        removed again in `finally`; `release` evicts the modules.
        """
        sys.path.insert(0, str(package_root))
        try:
            return importlib.import_module(dotted)
        finally:
            sys.path.remove(str(package_root))

    def invoke(
        self,
        loaded: LoadedExtension,
        context: ExtensionContext | None = None,
    ) -> Any:
        """Stage 5 — call the declared handler; containment is the contract.

        A handler that raises is wrapped in `HandlerRaised` with the
        original attached as `__cause__`: the host survives, the failure is
        typed, and later cases still run. After `request_cancel`, the host
        refuses to call the handler at all.
        """
        if loaded.cancelled:
            raise InvocationCancelled(
                f"invocation for {loaded.manifest.id!r} was cancelled before the "
                "call; the host never invoked the handler"
            )
        handler = _resolve_handler(loaded)
        try:
            return _call(handler, context or loaded.context)
        except ContractError:
            raise
        except Exception as exc:
            raise HandlerRaised(
                f"handler of {loaded.manifest.id!r} raised {type(exc).__name__}: {exc}"
            ) from exc

    def release(self, loaded: LoadedExtension) -> None:
        """Stage 6 — drop the module and everything it put on the path caches.

        The extension holds no state across releases; anything durable goes
        through declared, host-owned stores (which the harness, simulating
        locally, does not provide).
        """
        prefix = loaded.module.__name__.split(".")[0]
        for name in [
            name for name in sys.modules if name == prefix or name.startswith(prefix + ".")
        ]:
            sys.modules.pop(name, None)
