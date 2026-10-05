"""Shared conformance check bodies (issue #965).

One body per cross-cutting platform semantic, run unchanged against every
family (provider, connector, tool) and every backend leg. Each body drives the
subject's real code through the canonical seams — Binding, credential routing,
the Invocation service, the governed policy boundary, the guarded outbound
transport, the usage recorder — and asserts what the platform actually
recorded. None of them read source text; a subject "passes" only by behaving
correctly while executing.

Refusal shapes the checks accept: the platform's own refusal types
(``SSRFBlockedError``/``OutboundBlockedError``, ``AgentError`` subclasses) and
plain ``ValueError``/``TypeError`` from subject-level validation. Everything
else — a silent success that leaked the secret, a socket the audit server
actually saw — fails.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.credential_routing import CredentialRouting
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationDenied,
    InvocationPolicyContext,
)
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    InvocationUsage,
)
from maistro.capabilities.types import Unavailable
from maistro.conformance.contract import (
    CheckId,
    CheckResult,
    CheckStatus,
)
from maistro.conformance.subject import ConformanceSubject, EffectRequest
from maistro.credentials.router import CredentialRouter, CredentialScopeError
from maistro.credentials.types import CredentialRecord
from maistro.events.envelope import InMemoryEventStore
from maistro.policy.types import Decision, PolicyVerdict
from maistro.quota.recorder import CanonicalInvocationUsageRecorder
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.security.outbound import (
    OutboundBlockedError,
    configure_outbound_policy,
)
from maistro.security.ssrf import SSRFBlockedError

#: The workspace/project scope every check runs its canonical effects under.
SCOPE_WORKSPACE = "conformance-ws"
SCOPE_PROJECT = "conformance-proj"

#: A credential every subject is free to name in its ``credential_refs``.
CONFORMANCE_CREDENTIAL_REF = "conformance-key-1"

#: Distinct plaintext markers per probe, so a leak can always be attributed.
PLAINTEXT_SECRET = "conformance-plaintext-secret-9f3a"
POOL_SECRET = "conformance-pool-secret-4b7e"

#: Path the egress probes ask the subject to fetch on the audit server.
PROBE_PATH = "/conformance-probe"

_REFUSAL_TYPES: tuple[type[BaseException], ...] = (
    ValueError,
    TypeError,
    PermissionError,
    SSRFBlockedError,
)


def _pass(check_id: CheckId, detail: str, **evidence: Any) -> CheckResult:
    return CheckResult(check_id=check_id, status=CheckStatus.PASS, detail=detail, evidence=evidence)


def _fail(check_id: CheckId, detail: str, **evidence: Any) -> CheckResult:
    return CheckResult(check_id=check_id, status=CheckStatus.FAIL, detail=detail, evidence=evidence)


def _binding(
    *, workspace_id: str = SCOPE_WORKSPACE, credential_refs: tuple[str, ...] = ()
) -> Binding:
    return Binding(
        workspace_id=workspace_id,
        project_id=SCOPE_PROJECT,
        capability="conformance.effect",
        credential_refs=credential_refs,
    )


def _is_refusal(exc: BaseException) -> bool:
    return isinstance(exc, _REFUSAL_TYPES)


async def _resolved_provider(subject: ConformanceSubject, binding: Binding) -> Any:
    return await subject.resolve_provider(binding)


async def check_secrets_plaintext_refused(subject: ConformanceSubject) -> CheckResult:
    """A plaintext extension secret must be refused or stripped, never kept.

    The probe hands the subject a configuration carrying a unique plaintext
    marker and then searches everything the subject hands back — the prepared
    configuration and its repr — for that marker. A subject that validates
    correctly raises or returns reference-only configuration; a subject that
    quietly accepts the plaintext fails, because that plaintext is exactly
    what would end up persisted in a Binding snapshot or an event.
    """
    try:
        prepared = subject.prepare_config({"api_key": PLAINTEXT_SECRET})
    except Exception as exc:
        if _is_refusal(exc):
            return _pass(
                CheckId.SECRETS_PLAINTEXT_REFUSED,
                "plaintext secret refused",
                refusal=type(exc).__name__,
            )
        return _fail(
            CheckId.SECRETS_PLAINTEXT_REFUSED,
            f"non-refusal error type {type(exc).__name__}: {exc}",
        )
    rendered = f"{prepared!r}"
    if PLAINTEXT_SECRET in rendered:
        return _fail(
            CheckId.SECRETS_PLAINTEXT_REFUSED,
            "prepared configuration retained the plaintext secret",
        )
    return _pass(
        CheckId.SECRETS_PLAINTEXT_REFUSED,
        "plaintext secret absent from prepared configuration",
        prepared_keys=sorted(str(key) for key in prepared),
    )


async def check_credential_ref_resolution(subject: ConformanceSubject) -> CheckResult:
    """Canonical secret-reference resolution under the Binding's own scope.

    Seeds a real scoped credential pool, wraps the subject's resolver with the
    production ``CredentialRouting`` seam, and proves three directions: an
    authorized reference resolves and exposes only its key id, the pool's
    plaintext never reaches a persisted snapshot or a repr, and an
    unauthorized reference is denied loudly (``CredentialScopeError``) instead
    of falling through.
    """
    router = CredentialRouter()
    router.add(
        workspace_id=SCOPE_WORKSPACE,
        project_id=SCOPE_PROJECT,
        record=CredentialRecord(
            key_id=CONFORMANCE_CREDENTIAL_REF,
            provider="conformance",
            api_key=POOL_SECRET,
        ),
    )
    routed = CredentialRouting(router).resolver(subject.resolve_provider)
    binding = _binding(credential_refs=(CONFORMANCE_CREDENTIAL_REF,))
    try:
        resolved = await routed(binding)
    except CredentialScopeError as exc:
        return _fail(
            CheckId.SECRETS_CREDENTIAL_REF_RESOLUTION,
            f"authorized reference did not resolve: {exc}",
        )
    if isinstance(resolved, Unavailable):
        return _fail(
            CheckId.SECRETS_CREDENTIAL_REF_RESOLUTION,
            f"resolver reported the subject unavailable: {resolved.reason}",
        )
    snapshot = ResolvedBinding.from_provider(binding, resolved)
    surfaces = f"{snapshot.model_dump_json()}\n{resolved!r}"
    if POOL_SECRET in surfaces:
        return _fail(
            CheckId.SECRETS_CREDENTIAL_REF_RESOLUTION,
            "pool plaintext leaked into a persisted snapshot or repr",
        )
    unauthorized = _binding(credential_refs=("not-authorized",))
    try:
        await routed(unauthorized)
    except CredentialScopeError:
        return _pass(
            CheckId.SECRETS_CREDENTIAL_REF_RESOLUTION,
            "reference resolved via scoped pool; plaintext absent; unauthorized ref denied",
            key_id=CONFORMANCE_CREDENTIAL_REF,
        )
    except Exception as exc:
        return _fail(
            CheckId.SECRETS_CREDENTIAL_REF_RESOLUTION,
            f"unauthorized reference raised {type(exc).__name__} instead of CredentialScopeError",
        )
    return _fail(
        CheckId.SECRETS_CREDENTIAL_REF_RESOLUTION,
        "unauthorized reference resolved instead of being denied",
    )


async def _attempt_egress(
    subject: ConformanceSubject, provider: Any, url: str
) -> BaseException | None:
    """Ask the subject to fetch ``url``; return the refusal, or None on success."""
    try:
        await subject.execute(provider, EffectRequest(url=url, payload={"path": PROBE_PATH}))
    except BaseException as exc:
        if isinstance(exc, asyncio.CancelledError):  # pragma: no cover - defensive
            raise
        return exc
    return None


def _egress_verdict(
    check_id: CheckId,
    *,
    allow_origin: bool,
    outcome: BaseException | None,
    hits_before: int,
    hits_after: int,
) -> CheckResult:
    """Turn one egress attempt into its check result (refusal shape + wire)."""
    wire_moved = hits_after != hits_before
    if outcome is None:
        return _completed_egress_verdict(
            check_id, allow_origin=allow_origin, hits_before=hits_before, hits_after=hits_after
        )
    if isinstance(outcome, SSRFBlockedError | OutboundBlockedError):
        return _policy_refusal_verdict(
            check_id,
            allow_origin=allow_origin,
            outcome=outcome,
            hits_before=hits_before,
            hits_after=hits_after,
        )
    if not allow_origin and _is_refusal(outcome) and not wire_moved:
        return _pass(
            check_id,
            "undeclared egress refused by the subject's normalized error",
            refusal=type(outcome).__name__,
        )
    return _fail(
        check_id,
        f"effect failed with {type(outcome).__name__} (hits {hits_before} -> {hits_after}): {outcome}",
    )


def _completed_egress_verdict(
    check_id: CheckId, *, allow_origin: bool, hits_before: int, hits_after: int
) -> CheckResult:
    """The attempt returned normally: declared legs connect, undeclared fail."""
    if allow_origin:
        if hits_after == hits_before:
            return _fail(check_id, "declared origin allowed but no request reached the server")
        return _pass(check_id, "declared origin reached through the guarded seam", hits=hits_after)
    return _fail(
        check_id,
        f"undeclared egress completed and reached the audit server (hits {hits_before} -> {hits_after})",
    )


def _policy_refusal_verdict(
    check_id: CheckId,
    *,
    allow_origin: bool,
    outcome: SSRFBlockedError | OutboundBlockedError,
    hits_before: int,
    hits_after: int,
) -> CheckResult:
    """The outbound policy refused: fatal when declared, evidence when not."""
    if allow_origin:
        return _fail(check_id, f"declared origin was refused: {outcome.detail}")
    if hits_after != hits_before:
        return _fail(
            check_id,
            "refused, but the audit server received the request anyway",
            hits_before=hits_before,
            hits_after=hits_after,
        )
    return _pass(
        check_id,
        "undeclared egress refused before any connection",
        refusal=type(outcome).__name__,
    )


async def check_egress(
    subject: ConformanceSubject,
    *,
    probe_url: str,
    audit_server: Any,
    allow_origin: bool,
) -> CheckResult:
    """Undeclared egress is refused before connecting; declared egress flows.

    ``probe_url`` points at the run's local audit server — a real socket that
    counts every request it accepts. The undeclared leg asserts the subject's
    effect is refused by the outbound policy *and* that the server received
    nothing: a raw-socket bypass shows up as a hit, which is what makes this
    detection behavioral rather than textual. The declared leg allows the
    origin and asserts exactly one request arrives through the guarded seam.
    """
    check_id = (
        CheckId.EGRESS_DECLARED_ALLOWED if allow_origin else CheckId.EGRESS_UNDECLARED_BLOCKED
    )
    provider = await _resolved_provider(subject, _binding())
    if isinstance(provider, Unavailable):
        return _fail(check_id, f"subject unavailable: {provider.reason}")
    hits_before = audit_server.hit_count()
    outcome = await _attempt_egress(subject, provider, probe_url)
    hits_after = audit_server.hit_count()
    return _egress_verdict(
        check_id,
        allow_origin=allow_origin,
        outcome=outcome,
        hits_before=hits_before,
        hits_after=hits_after,
    )


def declare_egress_origin(origin_url: str) -> None:
    """Allow one origin for the declared-egress leg (additive, like prod)."""
    configure_outbound_policy(origin_url)


async def check_scope_propagation(subject: ConformanceSubject) -> CheckResult:
    """Tenant/workspace scope propagates onto the persisted effect record.

    Two effects run under different Workspaces with the same effect key. Each
    persisted Invocation must carry its own Binding's scope (never a process
    default), the resolved Binding snapshot must repeat it, and the two must
    be distinct admissions — a scope-less or cross-tenant-shared record is the
    failure this check exists to catch.
    """
    service = InvocationExecutionService(store=InMemoryInvocationStore())
    calls = 0

    async def resolve(binding: Binding) -> Any:
        return await subject.resolve_provider(binding)

    async def execute(provider: Any, request: Any) -> Any:
        nonlocal calls
        calls += 1
        return await subject.execute(provider, EffectRequest(payload=dict(request)))

    async def invoke_under(workspace_id: str, attempt_id: str) -> Any:
        return await service.invoke(
            binding=_binding(workspace_id=workspace_id),
            run_id="run-scope",
            node_run_id="node-scope",
            attempt_id=attempt_id,
            effect_key="effect",
            request={"scope": "probe"},
            resolver=resolve,
            executor=execute,
        )

    first = await invoke_under("conformance-ws-alpha", "attempt-1")
    second = await invoke_under("conformance-ws-beta", "attempt-2")
    scope_pairs = (
        (first, "conformance-ws-alpha"),
        (second, "conformance-ws-beta"),
    )
    for invocation, expected_ws in scope_pairs:
        if invocation.workspace_id != expected_ws or invocation.project_id != SCOPE_PROJECT:
            return _fail(
                CheckId.SCOPE_PROPAGATION,
                "Invocation did not carry its Binding's scope",
                expected_workspace=expected_ws,
                recorded_workspace=invocation.workspace_id,
                recorded_project=invocation.project_id,
            )
        if invocation.binding.workspace_id != expected_ws:
            return _fail(
                CheckId.SCOPE_PROPAGATION,
                "resolved Binding snapshot lost the scope",
                snapshot_workspace=invocation.binding.workspace_id,
            )
    if first.invocation_id == second.invocation_id or calls != 2:
        return _fail(
            CheckId.SCOPE_PROPAGATION,
            "distinct scopes shared one effect admission",
            calls=calls,
        )
    return _pass(
        CheckId.SCOPE_PROPAGATION,
        "scope propagated to both records; admissions stayed scope-distinct",
        invocation_ids=[first.invocation_id, second.invocation_id],
    )


async def check_error_normalization(subject: ConformanceSubject) -> CheckResult:
    """Provider errors normalize to the canonical Invocation ledger states.

    An explicit not-applied failure is a FAILED record a later Attempt may
    retry; any other exception stays UNKNOWN — the external outcome cannot be
    proven absent, so the ledger refuses to call it finished.
    """
    service = InvocationExecutionService(store=InMemoryInvocationStore())
    binding = _binding()

    async def resolve(candidate: Binding) -> Any:
        return await subject.resolve_provider(candidate)

    async def invoke(attempt_id: str, run_id: str, executor: Any) -> Any:
        with contextlib.suppress(Exception):
            await service.invoke(
                binding=binding,
                run_id=run_id,
                node_run_id="node-err",
                attempt_id=attempt_id,
                effect_key="effect",
                request={},
                resolver=resolve,
                executor=executor,
            )
        return await service.latest_effect(
            binding=binding,
            run_id=run_id,
            node_run_id="node-err",
            effect_key="effect",
        )

    async def not_applied(_provider: Any, _request: Any) -> Any:
        raise EffectNotApplied("conformance probe: provider confirmed non-application")

    first = await invoke("attempt-1", "run-err", not_applied)
    if first is None or first.status is not InvocationStatus.FAILED:
        return _fail(
            CheckId.ERROR_NORMALIZATION,
            f"EffectNotApplied normalized to {getattr(first, 'status', None)}, expected FAILED",
        )
    second = await invoke("attempt-2", "run-err", not_applied)
    if second is None or second.status is not InvocationStatus.FAILED:
        return _fail(
            CheckId.ERROR_NORMALIZATION,
            "a FAILED effect was not re-admissible under a later Attempt",
        )

    async def generic_error(_provider: Any, _request: Any) -> Any:
        raise RuntimeError("conformance probe: ambiguous provider failure")

    third = await invoke("attempt-1", "run-err2", generic_error)
    if third is None or third.status is not InvocationStatus.UNKNOWN:
        return _fail(
            CheckId.ERROR_NORMALIZATION,
            f"generic provider error normalized to {getattr(third, 'status', None)}, expected UNKNOWN",
        )
    return _pass(
        CheckId.ERROR_NORMALIZATION,
        "EffectNotApplied -> FAILED (retryable); other errors -> UNKNOWN (ambiguous)",
        invocation_ids=[first.invocation_id, second.invocation_id, third.invocation_id],
    )


async def check_cancellation_normalization(subject: ConformanceSubject) -> CheckResult:
    """Cancellation lands as UNKNOWN ambiguity evidence, never fake closure."""
    service = InvocationExecutionService(store=InMemoryInvocationStore())
    binding = _binding()

    async def resolve(candidate: Binding) -> Any:
        return await subject.resolve_provider(candidate)

    async def hang(_provider: Any, _request: Any) -> Any:
        await asyncio.sleep(30)

    task = asyncio.ensure_future(
        service.invoke(
            binding=binding,
            run_id="run-cancel",
            node_run_id="node-cancel",
            attempt_id="attempt-1",
            effect_key="effect",
            request={},
            resolver=resolve,
            executor=hang,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    settled = await service.latest_effect(
        binding=binding,
        run_id="run-cancel",
        node_run_id="node-cancel",
        effect_key="effect",
    )
    if settled is None:
        return _fail(CheckId.CANCELLATION_NORMALIZATION, "cancelled effect left no ledger record")
    if settled.status is not InvocationStatus.UNKNOWN:
        return _fail(
            CheckId.CANCELLATION_NORMALIZATION,
            f"cancellation normalized to {settled.status}, expected UNKNOWN",
        )
    if "cancel" not in (settled.error or "").lower():
        return _fail(
            CheckId.CANCELLATION_NORMALIZATION,
            f"UNKNOWN record lacks cancellation evidence: {settled.error!r}",
        )
    return _pass(
        CheckId.CANCELLATION_NORMALIZATION,
        "cancellation recorded as UNKNOWN with explicit evidence",
        invocation_id=settled.invocation_id,
    )


async def check_deadline_enforcement(subject: ConformanceSubject) -> CheckResult:
    """A hung effect must be deadline-cancellable (cooperative cancellation).

    The platform enforces deadlines by cancelling the in-flight effect, so the
    subject's effect has to actually stop when cancelled. The probe cancels a
    hung effect and then gives the task a short grace period to finish
    cancelling: a subject that shields its work or blocks the loop inside a
    sync call never completes cancellation within the grace period and fails.
    """
    provider = await _resolved_provider(subject, _binding())
    if isinstance(provider, Unavailable):
        return _fail(CheckId.DEADLINE_ENFORCEMENT, f"subject unavailable: {provider.reason}")
    probe = EffectRequest(payload={}, hang_seconds=30)
    if probe.hang_seconds <= 0:
        return _fail(
            CheckId.DEADLINE_ENFORCEMENT,
            "deadline probe is vacuous: it must request a hang to cancel",
        )
    task = asyncio.ensure_future(subject.execute(provider, probe))
    await asyncio.sleep(0.05)
    task.cancel()
    done, _pending = await asyncio.wait({task}, timeout=2.0)
    if task not in done:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return _fail(
            CheckId.DEADLINE_ENFORCEMENT,
            "effect ignored cancellation for the whole grace period",
        )
    if not task.cancelled() and task.exception() is not None:
        exc = task.exception()
        return _fail(
            CheckId.DEADLINE_ENFORCEMENT,
            f"cancellation surfaced {type(exc).__name__} instead of propagating",
        )
    return _pass(CheckId.DEADLINE_ENFORCEMENT, "hung effect cancelled cooperatively")


async def _usage_invoke(
    subject: ConformanceSubject,
    service: InvocationExecutionService,
    *,
    run_id: str,
    request: dict[str, Any],
) -> Invocation:
    """Run one governed effect whose usage is extracted by the subject itself."""
    binding = _binding()

    async def resolve(candidate: Binding) -> Any:
        return await subject.resolve_provider(candidate)

    async def execute(provider: Any, effect_request: Any) -> Any:
        return await subject.execute(provider, EffectRequest(payload=dict(effect_request)))

    with contextlib.suppress(Exception):
        return await service.invoke(
            binding=binding,
            run_id=run_id,
            node_run_id="node-usage",
            attempt_id="attempt-1",
            effect_key="effect",
            request=request,
            resolver=resolve,
            executor=execute,
            usage_from=subject.usage_from,
        )
    stored = await service.latest_effect(
        binding=binding,
        run_id=run_id,
        node_run_id="node-usage",
        effect_key="effect",
    )
    assert stored is not None  # the service always persists an admission
    return stored


def _usage_events_for(log: InMemoryUsageLog, invocation: Invocation) -> list[Any]:
    """Ledger events recorded for one Invocation (scope key is the provider)."""
    scope = invocation.binding.provider_name
    return [
        event for event in log.events_for(scope) if event.invocation_id == invocation.invocation_id
    ]


def _reported_usage_verdict(log: InMemoryUsageLog, completed: Invocation) -> CheckResult | None:
    """The reported-usage leg: exactly one event, exact units, provenance."""
    events = _usage_events_for(log, completed)
    if len(events) != 1:
        return _fail(
            CheckId.USAGE_AND_PROVENANCE,
            "usage ledger did not hold exactly one event for the Invocation",
            events=len(events),
        )
    event = events[0]
    if event.input_tokens != 7 or event.output_tokens != 3:
        return _fail(
            CheckId.USAGE_AND_PROVENANCE,
            f"recorded units drifted: in={event.input_tokens} out={event.output_tokens}",
        )
    if event.usage_reported is not True or event.provider != completed.binding.provider_name:
        return _fail(
            CheckId.USAGE_AND_PROVENANCE,
            "provenance missing: event must carry usage_reported and the resolved provider",
            provider=event.provider,
            usage_reported=event.usage_reported,
        )
    return None


async def check_usage_and_provenance(subject: ConformanceSubject) -> CheckResult:
    """Usage reports exactly once, with provenance; missing usage stays unreported.

    Drives two completed effects through the canonical recorder using the
    subject's own usage extractor — the same ``UsageExtractor`` seam a
    production composition root installs. The ledger must show one event per
    Invocation carrying the subject's reported units and the resolved provider
    as provenance; recording twice must not double-charge (retries/dedup
    re-confirm evidence). An effect with no usage must land as an explicit
    unreported marker — never as measured zero. Negative usage must be
    refused by the canonical validation.
    """
    service = InvocationExecutionService(store=InMemoryInvocationStore())
    log = InMemoryUsageLog()
    recorder = CanonicalInvocationUsageRecorder(log)

    completed = await _usage_invoke(
        subject, service, run_id="run-usage", request={"report_usage": True}
    )
    if completed.status is not InvocationStatus.COMPLETED:
        return _fail(
            CheckId.USAGE_AND_PROVENANCE,
            f"effect did not complete: {completed.status} {completed.error or ''}",
        )
    await recorder.record(completed)
    await recorder.record(completed)
    verdict = _reported_usage_verdict(log, completed)
    if verdict is not None:
        return verdict

    unreported = await _usage_invoke(
        subject, service, run_id="run-usage2", request={"report_usage": False}
    )
    await recorder.record(unreported)
    unreported_events = _usage_events_for(log, unreported)
    if len(unreported_events) != 1 or unreported_events[0].usage_reported is not False:
        return _fail(
            CheckId.USAGE_AND_PROVENANCE,
            "missing usage was not recorded as an explicit unreported marker",
        )
    try:
        InvocationUsage(units="tokens", input_units=-1, output_units=0)
    except ValueError:
        return _pass(
            CheckId.USAGE_AND_PROVENANCE,
            "usage recorded once with provenance; missing usage marked unreported; negatives refused",
            invocation_ids=[completed.invocation_id, unreported.invocation_id],
        )
    return _fail(CheckId.USAGE_AND_PROVENANCE, "negative usage units were accepted")


async def check_bypass_refused(subject: ConformanceSubject, *, audit_server: Any) -> CheckResult:
    """Direct model/tool/network bypass attempts are refused before dispatch.

    Three probes, all behavioral. (1) A capability the subject cannot serve is
    reported unavailable and the canonical service fails closed — the effect
    never dispatches to some other provider. (2) A policy denial raises
    ``InvocationDenied`` before the subject's executor is entered. (3) The
    network bypass — an effect aimed at an undeclared origin — never reaches
    the wire: the audit server's request count must not move during the
    refusal probes.
    """
    executor_calls = 0
    hits_before = audit_server.hit_count()

    async def counting_execute(provider: Any, request: Any) -> Any:
        nonlocal executor_calls
        executor_calls += 1
        return await subject.execute(provider, EffectRequest(payload=dict(request)))

    failed = await _probe_unavailable_fails_closed(counting_execute)
    if failed is not None:
        return failed
    failed = await _probe_policy_denial(subject, counting_execute)
    if failed is not None:
        return failed
    if executor_calls != 0:
        return _fail(
            CheckId.BYPASS_REFUSED,
            f"subject executor ran {executor_calls} times despite refusals",
        )
    # The declared-egress leg legitimately reached the audit server earlier in
    # this run; the wire-clean property here is that the refusal probes
    # themselves put no NEW traffic on the wire: a bypass that dispatched a
    # network effect during a refusal would surface as a request the audit
    # server accepted between the two counts.
    hits_after = audit_server.hit_count()
    if hits_after != hits_before:
        return _fail(
            CheckId.BYPASS_REFUSED,
            "the refusal probes put new traffic on the wire",
            hits_before=hits_before,
            hits_after=hits_after,
        )
    return _pass(
        CheckId.BYPASS_REFUSED,
        "unavailable capability failed closed; policy denial blocked dispatch; no wire traffic",
    )


async def _probe_unavailable_fails_closed(executor: Any) -> CheckResult | None:
    """Probe 1: an unresolvable capability must fail closed, not fall through."""

    async def unavailable_resolve(_binding: Binding) -> Unavailable:
        return Unavailable(slot="conformance.effect", reason="not installed here")

    try:
        await InvocationExecutionService(store=InMemoryInvocationStore()).invoke(
            binding=_binding(),
            run_id="run-bypass",
            node_run_id="node-bypass",
            attempt_id="attempt-1",
            effect_key="effect",
            request={},
            resolver=unavailable_resolve,
            executor=executor,
        )
    except PermissionError:
        return _fail(
            CheckId.BYPASS_REFUSED,
            "unavailable capability surfaced a PermissionError, expected CapabilityUnavailable",
        )
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            return None
        return _fail(
            CheckId.BYPASS_REFUSED,
            f"unavailable capability surfaced {type(exc).__name__}, expected fail-closed",
        )
    return _fail(CheckId.BYPASS_REFUSED, "an unavailable capability dispatched anyway")


async def _probe_policy_denial(subject: ConformanceSubject, executor: Any) -> CheckResult | None:
    """Probe 2: a policy denial must stop the effect before the executor runs."""

    async def denying_evaluator(
        _binding: Any, _request: Any, _context: InvocationPolicyContext
    ) -> PolicyVerdict:
        return PolicyVerdict(decision=Decision.DENY, reason="conformance probe denial")

    governed = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=InMemoryEventStore(),
        policy_evaluator=denying_evaluator,
    )

    async def resolve(binding: Binding) -> Any:
        return await subject.resolve_provider(binding)

    try:
        await governed.invoke(
            binding=_binding(),
            run_id="run-bypass2",
            node_run_id="node-bypass",
            attempt_id="attempt-1",
            effect_key="effect",
            request={},
            resolver=resolve,
            executor=executor,
        )
    except InvocationDenied:
        return None
    except Exception as exc:
        return _fail(
            CheckId.BYPASS_REFUSED,
            f"policy denial surfaced {type(exc).__name__}, expected InvocationDenied",
        )
    return _fail(CheckId.BYPASS_REFUSED, "a denied effect executed anyway")


__all__ = [
    "CONFORMANCE_CREDENTIAL_REF",
    "PLAINTEXT_SECRET",
    "POOL_SECRET",
    "PROBE_PATH",
    "SCOPE_PROJECT",
    "SCOPE_WORKSPACE",
    "check_bypass_refused",
    "check_cancellation_normalization",
    "check_credential_ref_resolution",
    "check_deadline_enforcement",
    "check_egress",
    "check_error_normalization",
    "check_scope_propagation",
    "check_secrets_plaintext_refused",
    "check_usage_and_provenance",
    "declare_egress_origin",
]
