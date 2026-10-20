"""Governed execution harness for code-registry refs (ADR-069).

SPEC-257 built only the resolve/verify core; the convergence note on ADR-069
records that the registry was reachable-by-design from an ``invoke()`` that
was never built. This module is that ``invoke()`` (#59): every execution of a
signed code ref crosses one fail-closed boundary —

1. ``resolve()`` — signature is re-verified at this admission point, catching
   tampering between registration and execution;
2. **Sentinel authorization** (ADR-068) — the same tool-call envelope as any
   other effect; a ref cannot acquire privilege its principal lacks;
3. **Warden payload scan** — untrusted input risk-scanned like every other
   boundary crossing;
4. **Sandbox isolation** — an untrusted ref without a sandbox runtime is
   *refused* (``isolation == "refused"``), never run unconfined, and the
   result's isolation label reports what actually ran the code.

The harness owns no dispatch semantics and no second authorization path: it
composes the accepted authorities (CodeRegistry, Sentinel, Warden, a
substitutable sandbox executor) exactly like ``capabilities.effect_context``
composes Binding/Invocation for capability effects.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.code_registry.registry import CodeRegistry
from maistro.code_registry.types import CodeEntry, CodeKind

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from maistro.security.sentinel.authz_types import Principal

logger = logging.getLogger("maistro.code_registry.execution")

#: Honest label recorded when nothing ran the code (ADR-069 failure table).
ISOLATION_REFUSED = "refused"

#: Reversibility class per kind (ADR-050): registry code is internal
#: computation — a compensator/estimator/gate must never be classed as an
#: irreversible external effect, which would push it up the tier ladder for
#: the wrong reason.
_KIND_REVERSIBILITY = {
    CodeKind.COMPENSATOR: "reversible",
    CodeKind.IMPACT_ESTIMATOR: "reversible",
    CodeKind.IDEMPOTENCY_KEY: "reversible",
    CodeKind.MERGE_RESOLVER: "reversible",
    CodeKind.DYNAMIC_GATE: "reversible",
}


@dataclass(frozen=True)
class CodeSandboxOutcome:
    """What a sandbox executor actually did, in its own words.

    ``label`` is the honest isolation claim (``"hyperlight"``, ``"firecracker"``,
    ...) — the contract is that it names the real runtime, never a claim the
    executor cannot back (ADR-069: no over-claiming).
    """

    label: str
    result: Any = None


@runtime_checkable
class CodeSandbox(Protocol):
    """Substitutable microVM executor contract (ADR-069).

    Implementations receive the resolved, signature-verified entry and the
    (already authorized + scanned) payload, fetch the content-addressed body
    themselves, enforce the ADR-054 tier resource caps, and report the
    isolation actually achieved. A killed/over-budget execution raises, which
    the harness treats as an invocation failure per the ADR failure table.
    """

    async def execute(self, entry: CodeEntry, payload: Mapping[str, Any]) -> CodeSandboxOutcome: ...


@dataclass(frozen=True)
class CodeResult:
    """Outcome of one governed code invocation."""

    ref: str
    ok: bool
    isolation: str
    result: Any = None
    reason: str = ""


class CodeInvoker:
    """The ``invoke()`` half of the ADR-069 registry contract."""

    def __init__(
        self,
        registry: CodeRegistry,
        *,
        sentinel: Any = None,
        warden_scan: Callable[[str, str], Awaitable[Any]] | None = None,
        sandbox: CodeSandbox | None = None,
    ) -> None:
        self._registry = registry
        self._sentinel = sentinel
        self._warden_scan = warden_scan
        self._sandbox = sandbox

    async def invoke(
        self,
        ref: str,
        payload: Mapping[str, Any],
        principal: Principal,
    ) -> CodeResult:
        """Execute one signed code ref under the full governed envelope.

        Raises the registry's fail-closed errors (``CodeRefUnresolved``,
        ``InvalidSignature``) unchanged: an unresolvable ref at the call site
        is a load-time defect the caller must not swallow (ADR-053). Every
        *policy* refusal — authorization, payload scan, missing sandbox —
        returns ``CodeResult(ok=False, isolation="refused")`` instead.
        """
        # 1. Admission: resolve re-verifies the entry signature (SPEC-257
        #    core, #848 post-registration recheck).
        entry = self._registry.resolve(ref)

        # 2. Authorization: the ADR-068 envelope, not a private permission
        #    system. No Sentinel wired means no authorized execution at all.
        if self._sentinel is None:
            return self._refused(ref, "no authorization authority (Sentinel) wired")
        reversibility = _KIND_REVERSIBILITY.get(entry.kind, "reversible")
        decision = await self._sentinel.authorize(
            f"code.invoke.{entry.kind.value}",
            principal,
            reversibility=reversibility,
        )
        if not decision.authorized:
            return self._refused(ref, f"authorization denied: {decision.reason}")

        # 3. Warden risk scan of the untrusted payload (best-effort text form).
        if self._warden_scan is not None:
            verdict = await self._warden_scan(
                json.dumps(payload, default=str, sort_keys=True), "code_invoke"
            )
            blocked = getattr(verdict, "blocked", False)
            flags = getattr(verdict, "flags", ())
            if blocked:
                return self._refused(ref, f"warden blocked payload: {'; '.join(flags)}")

        # 4. Isolation: fail-closed. No sandbox runtime configured means the
        #    code does not run — for trusted engine-authored code too, since
        #    "lighter tier" is still a tier the deployment chose to provide.
        if self._sandbox is None:
            return self._refused(ref, "no sandbox runtime configured; refusing to run unconfined")
        try:
            outcome = await self._sandbox.execute(entry, payload)
        except Exception as exc:  # over-budget/failed microVM: invocation failure
            logger.warning("code invocation failed in sandbox: ref=%s error=%s", ref, exc)
            return CodeResult(ref=ref, ok=False, isolation=ISOLATION_REFUSED, reason=str(exc))
        return CodeResult(
            ref=ref,
            ok=True,
            isolation=outcome.label,
            result=outcome.result,
        )

    @staticmethod
    def _refused(ref: str, reason: str) -> CodeResult:
        logger.warning("code invocation REFUSED: ref=%s reason=%s", ref, reason)
        return CodeResult(ref=ref, ok=False, isolation=ISOLATION_REFUSED, reason=reason)


__all__ = [
    "ISOLATION_REFUSED",
    "CodeInvoker",
    "CodeResult",
    "CodeSandbox",
    "CodeSandboxOutcome",
]
