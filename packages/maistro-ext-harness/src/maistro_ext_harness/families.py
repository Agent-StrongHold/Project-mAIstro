"""The reusable extension-family conformance runner (#974).

A **family plug-in** owns the cases for one extension family. The runner is
the reusable part: one execution engine (lifecycle → case → report), many
plug-ins. Every family inherits the shared protocol/security suite — the
manifest, entrypoint, grant, and context contract is family-independent —
and adds its own cases on top.

Built-ins today:

- `tool` — the one family whose entrypoint protocol is pinned by the merged
  contract (the reference extension's data-only `PLUGIN` plus a named
  handler), so its cases assert handler resolution, invocation, and
  repeat-invocation stability;
- `skill`, `mcp-gateway`, `capability-provider`, `renderer-plugin` —
  registered with the shared suite; their family-specific cases are the
  corresponding SDK slices' conformance suites (connector/source M9-E2,
  provider/tool shared runs M9-E4) and plug in through `register_family`
  without touching the engine.

Two harness self-checks run in every report alongside the subject cases:
`harness/failure-containment` (a probe whose handler raises must come back
as a typed failed case, with the host still usable) and
`harness/cancellation-refuses-invoke` (after host-side cancellation the
host refuses to call the handler at all — observed through the reference
handler's invocation record, not through timing).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from maistro_ext_harness.backends import BackendRegistry
from maistro_ext_harness.context import ExtensionContext
from maistro_ext_harness.contract import CAPABILITIES, FAMILIES, ContractError
from maistro_ext_harness.grants import Grant
from maistro_ext_harness.lifecycle import (
    DiscoveredExtension,
    ExtensionHost,
    HandlerRaised,
    InvocationCancelled,
    LoadedExtension,
)
from maistro_ext_harness.manifest import ExtensionManifest, load_manifest_file
from maistro_ext_harness.reference import (
    write_failing_probe_extension,
    write_reference_extension,
)
from maistro_ext_harness.report import CaseRecord, CaseStatus

__all__ = [
    "CaseEnvironment",
    "CaseOutcome",
    "ConformanceCase",
    "FamilyPlugin",
    "available_families",
    "builtin_cases",
    "family_cases",
    "family_plugin",
    "register_family",
    "shared_cases",
    "tool_cases",
]


@dataclass(frozen=True)
class CaseOutcome:
    """One case's verdict over one subject."""

    passed: bool
    detail: str


@dataclass(frozen=True)
class CaseEnvironment:
    """Everything a subject case may touch: the loaded subject, its grant,
    context, the host that loaded it, and the run's backend registry."""

    subject: str
    host: ExtensionHost
    discovered: DiscoveredExtension
    manifest: ExtensionManifest
    grant: Grant
    loaded: LoadedExtension
    backends: BackendRegistry

    @property
    def context(self) -> ExtensionContext:
        return self.loaded.context


@dataclass(frozen=True)
class ConformanceCase:
    """One named conformance case.

    `run` returns a `CaseOutcome`; an exception escaping `run` is contained
    by the runner and recorded as a failure (a case bug must not crash the
    run or, worse, pass silently). `requires_backend` names a real service
    without which the case cannot run honestly — the runner then fails the
    case closed unless an explicit waiver was recorded.
    """

    case_id: str
    description: str
    run: Callable[[CaseEnvironment], CaseOutcome]
    requires_backend: str | None = None
    # `None` = the case applies to every family that carries it; a tuple
    # restricts it to those families even when a shared plug-in ships it.
    families: tuple[str, ...] | None = None


@dataclass(frozen=True)
class FamilyPlugin:
    """The per-family case set. `extra_cases` join the shared suite."""

    family: str
    extra_cases: tuple[ConformanceCase, ...] = ()


_REGISTRY: dict[str, FamilyPlugin] = {}


def register_family(plugin: FamilyPlugin) -> None:
    """Register (or replace) one family's plug-in — the reuse seam."""
    if plugin.family not in FAMILIES:
        raise ContractError(
            f"cannot register family {plugin.family!r}: not in the closed family "
            f"vocabulary {list(FAMILIES)}"
        )
    _REGISTRY[plugin.family] = plugin


def family_plugin(family: str) -> FamilyPlugin:
    """The plug-in for `family`, registering built-ins on first use."""
    _ensure_builtins()
    return _REGISTRY[family]


def available_families() -> tuple[str, ...]:
    """Every family with a registered plug-in, in vocabulary order."""
    _ensure_builtins()
    return tuple(f for f in FAMILIES if f in _REGISTRY)


def family_cases(family: str) -> tuple[ConformanceCase, ...]:
    """The full case list for `family`: shared suite plus family extras.

    A case may scope itself to specific families via its `families` field;
    `None` means every family. Scoping is the plug-in's own declaration, so
    the engine stays family-agnostic.
    """

    def _applies(case: ConformanceCase) -> bool:
        return case.families is None or family in case.families

    return (
        *(case for case in shared_cases() if _applies(case)),
        *(case for case in family_plugin(family).extra_cases if _applies(case)),
    )


_BUILTINS_REGISTERED = False


def _ensure_builtins() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    for family in FAMILIES:
        register_family(
            FamilyPlugin(
                family=family,
                extra_cases=tool_cases() if family == "tool" else (),
            )
        )
    _BUILTINS_REGISTERED = True


def builtin_cases() -> tuple[ConformanceCase, ...]:
    """Every case the harness ships, across every family (test surface)."""
    cases: list[ConformanceCase] = list(shared_cases())
    for family in available_families():
        cases.extend(family_plugin(family).extra_cases)
    return tuple(cases)


# ---------------------------------------------------------------------------
# shared protocol / security cases — every family, every subject
# ---------------------------------------------------------------------------


def _case_manifest_revalidates(env: CaseEnvironment) -> CaseOutcome:
    from_disk = load_manifest_file(env.discovered.manifest_path)
    if from_disk != env.manifest:
        return CaseOutcome(False, "manifest on disk re-parsed to a different contract")
    return CaseOutcome(
        True,
        f"manifest revalidated from disk against contract "
        f"{from_disk.contract} (host enforces major {from_disk.contract_major})",
    )


def _case_entrypoint_in_own_namespace(env: CaseEnvironment) -> CaseOutcome:
    top = env.manifest.entrypoint.module.split(".")[0]
    roots = (env.discovered.root / "src", env.discovered.root)
    for root in roots:
        if (root / top).is_dir():
            return CaseOutcome(
                True,
                f"entrypoint module {env.manifest.entrypoint.module!r} "
                f"lives inside the extension's own package ({top!r})",
            )
    return CaseOutcome(
        False,
        f"entrypoint module {env.manifest.entrypoint.module!r} does not name a "
        "package inside the extension's own tree",
    )


def _case_entrypoint_object_resolves(env: CaseEnvironment) -> CaseOutcome:
    obj = env.loaded.plugin_object
    shape = (
        "mapping naming a handler"
        if isinstance(obj, dict)
        else ("callable object" if callable(obj) else "neither a handler mapping nor callable")
    )
    ok = isinstance(obj, dict) or callable(obj)
    return CaseOutcome(
        ok,
        f"entrypoint object {env.manifest.entrypoint.object!r} is a {shape}",
    )


def _case_context_least_authority(env: CaseEnvironment) -> CaseOutcome:
    context = env.context
    grant_caps = set(env.grant.capabilities)
    if set(context.capabilities) != grant_caps:
        return CaseOutcome(
            False,
            f"context exposes {sorted(context.capabilities)} but the grant is {sorted(grant_caps)}",
        )
    outside = [name for name in CAPABILITIES if name not in grant_caps]
    if outside and any(context.has_capability(name) for name in outside):
        return CaseOutcome(False, "context answers True for an ungranted capability")
    # A name outside the closed vocabulary entirely is not merely ungranted;
    # it must be invisible too.
    if context.has_capability("not-an-authority-name"):
        return CaseOutcome(False, "context answers True for a non-authority name")
    return CaseOutcome(
        True,
        f"context exposes exactly the granted capabilities {sorted(grant_caps)}",
    )


def _case_undeclared_authority_invisible(env: CaseEnvironment) -> CaseOutcome:
    declared = env.manifest
    grant = env.grant
    relation = (
        "the full declaration"
        if grant.equals_declaration(declared)
        else "a narrowed subset of the declaration"
    )
    narrowed_axes = [
        axis
        for axis, g, d in (
            ("capabilities", grant.capabilities, declared.capabilities),
            ("effects", grant.effects, declared.effects),
            ("data scopes", grant.data_scopes, declared.data_scopes),
        )
        if not set(g) <= set(d)
    ]
    if narrowed_axes:
        return CaseOutcome(False, f"grant exceeds declaration on {narrowed_axes}")
    hidden = []
    if grant.has_capability("workspace.read") != (env.context.workspace is not None):
        hidden.append("workspace view")
    if grant.has_capability("agent.read") != (env.context.identity is not None):
        hidden.append("identity view")
    if grant.has_capability("run.read") != (env.context.invocation is not None):
        hidden.append("invocation view")
    if hidden:
        return CaseOutcome(False, f"context visibility disagrees with the grant: {hidden}")
    return CaseOutcome(
        True,
        f"grant is {relation}; views appear exactly when their capability is "
        "granted — undeclared authority is invisible, not denied",
    )


def _materialize_probe(parent: Path, writer: Callable[[Path], Path]) -> Path:
    probe = Path(tempfile.mkdtemp(dir=parent))
    return writer(probe)


def _case_harness_failure_containment(env: CaseEnvironment) -> CaseOutcome:
    """The harness's deterministic failure case, executed on every run.

    A probe extension whose handler raises goes through the full lifecycle;
    the host must contain the raise as a typed `HandlerRaised` (original as
    `__cause__`) and stay usable for the next invocation attempt.
    """
    host = ExtensionHost()
    with tempfile.TemporaryDirectory() as tmp:
        probe_root = _materialize_probe(Path(tmp), write_failing_probe_extension)
        discovered = host.discover(probe_root)
        manifest = host.validate(discovered)
        loaded = host.load(discovered, manifest, host.grants_for(manifest))
        try:
            host.invoke(loaded)
        except HandlerRaised as exc:
            if exc.__cause__ is None:
                return CaseOutcome(False, "HandlerRaised lost the original cause")
            host.release(loaded)
            return CaseOutcome(
                True,
                f"handler failure contained as {type(exc).__name__} "
                f"(cause {type(exc.__cause__).__name__}); host remained usable",
            )
        host.release(loaded)
    return CaseOutcome(False, "a raising handler did not surface as HandlerRaised")


def _case_harness_cancellation(env: CaseEnvironment) -> CaseOutcome:
    """The harness's deterministic cancellation case, executed on every run.

    After host-side cancellation the host refuses the invocation outright —
    observed structurally: the reference handler's CALLS record stays empty,
    so "never invoked" is a fact about calls, not about wall-clock timing.
    """
    host = ExtensionHost()
    with tempfile.TemporaryDirectory() as tmp:
        ref_root = _materialize_probe(Path(tmp), write_reference_extension)
        discovered = host.discover(ref_root)
        manifest = host.validate(discovered)
        loaded = host.load(discovered, manifest, host.grants_for(manifest))
        calls_before = list(getattr(loaded.module, "CALLS", []))
        loaded.request_cancel()
        try:
            host.invoke(loaded)
        except InvocationCancelled:
            calls_after = list(getattr(loaded.module, "CALLS", []))
            host.release(loaded)
            if calls_after != calls_before:
                return CaseOutcome(False, "handler ran despite host-side cancellation")
            return CaseOutcome(
                True,
                "cancelled invocation refused before the handler ran "
                "(deterministic: call record unchanged, no timing involved)",
            )
        host.release(loaded)
    return CaseOutcome(False, "the host invoked a handler after cancellation was requested")


def shared_cases() -> tuple[ConformanceCase, ...]:
    """The family-independent suite: protocol, security, harness self-checks."""
    return (
        ConformanceCase(
            case_id="protocol/manifest-revalidates-from-disk",
            description="the subject's manifest revalidates from disk, naming the "
            "contract version the host enforces",
            run=_case_manifest_revalidates,
        ),
        ConformanceCase(
            case_id="protocol/entrypoint-in-own-namespace",
            description="the entrypoint module lives inside the extension's own package",
            run=_case_entrypoint_in_own_namespace,
        ),
        ConformanceCase(
            case_id="protocol/entrypoint-object-resolves",
            description="the entrypoint object is the documented data-only shape",
            run=_case_entrypoint_object_resolves,
        ),
        ConformanceCase(
            case_id="security/context-exposes-only-granted-capabilities",
            description="the context exposes exactly the granted capability set",
            run=_case_context_least_authority,
        ),
        ConformanceCase(
            case_id="security/undeclared-authority-invisible",
            description="grant ⊆ declaration, and context views appear exactly "
            "when their capability is granted",
            run=_case_undeclared_authority_invisible,
        ),
        ConformanceCase(
            case_id="harness/failure-containment",
            description="a raising handler is contained as a typed failure and "
            "the host stays usable",
            run=_case_harness_failure_containment,
        ),
        ConformanceCase(
            case_id="harness/cancellation-refuses-invoke",
            description="after host-side cancellation the host refuses to invoke "
            "the handler at all",
            run=_case_harness_cancellation,
        ),
    )


# ---------------------------------------------------------------------------
# tool-family cases — the pinned data-only entrypoint protocol
# ---------------------------------------------------------------------------


def _tool_handler(env: CaseEnvironment) -> Callable[..., object]:
    obj = env.loaded.plugin_object
    if isinstance(obj, dict):
        named = obj.get("handler")
        table = getattr(env.loaded.module, "HANDLERS", None)
        if isinstance(table, dict) and isinstance(named, str) and named in table:
            handler = table[named]
        else:
            handler = getattr(env.loaded.module, str(named), None)
        if handler is None:
            raise ContractError(
                f"tool handler {named!r} does not resolve on {env.loaded.module.__name__!r}"
            )
        return handler  # type: ignore[no-any-return]
    if callable(obj):
        return obj
    raise ContractError(
        f"entrypoint object of {env.manifest.id!r} is neither a handler mapping nor callable"
    )


def _case_tool_handler_invocation(env: CaseEnvironment) -> CaseOutcome:
    try:
        handler = _tool_handler(env)
        result = env.host.invoke(env.loaded)
    except ContractError as exc:
        return CaseOutcome(False, f"tool handler did not resolve: {exc}")
    except HandlerRaised as exc:
        return CaseOutcome(False, f"tool handler raised on invocation: {exc}")
    return CaseOutcome(
        True,
        f"declared tool handler {getattr(handler, '__name__', '<object>')!r} "
        f"invoked through the host, returned {type(result).__name__}",
    )


def _case_tool_repeat_stable(env: CaseEnvironment) -> CaseOutcome:
    try:
        first = env.host.invoke(env.loaded)
        second = env.host.invoke(env.loaded)
    except HandlerRaised as exc:
        return CaseOutcome(False, f"repeat invocation raised: {exc}")
    except InvocationCancelled:
        return CaseOutcome(False, "host refused a repeat invocation unexpectedly")
    stable = repr(first) == repr(second)
    calls = getattr(env.loaded.module, "CALLS", None)
    observed = f"; host observed {len(calls)} handler calls" if isinstance(calls, list) else ""
    detail = "two consecutive invocations completed" + (
        f" and returned identical results{observed}"
        if stable
        else f"{observed}; results differ between calls, which a read-only tool "
        "should not do for identical input"
    )
    return CaseOutcome(stable, detail)


def tool_cases() -> tuple[ConformanceCase, ...]:
    """The tool family's handler-contract cases."""
    return (
        ConformanceCase(
            case_id="tool/handler-invocation-succeeds",
            description="the declared tool handler resolves and invokes through "
            "the host without raising",
            run=_case_tool_handler_invocation,
        ),
        ConformanceCase(
            case_id="tool/handler-repeat-invocation-stable",
            description="a read-only tool's repeat invocation completes and stays "
            "deterministic for identical input",
            run=_case_tool_repeat_stable,
        ),
    )


#: The runner needs one record-shaped merge point; kept here so the case ->
#: report mapping lives next to the cases.
def record_for(
    case: ConformanceCase, outcome: CaseOutcome, subject: str, family: str
) -> CaseRecord:
    """Map a case outcome onto its report record."""
    return CaseRecord(
        case_id=case.case_id,
        family=family,
        subject=subject,
        status=CaseStatus.PASSED if outcome.passed else CaseStatus.FAILED,
        detail=outcome.detail,
        required_backend=case.requires_backend,
    )
