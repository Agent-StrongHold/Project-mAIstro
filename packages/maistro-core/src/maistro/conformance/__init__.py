"""Extension-family conformance suite (M9-E4, issue #965).

One shared suite proves that a third-party provider, connector, or tool obeys
the same cross-cutting platform semantics as supported built-ins:

* canonical secret-reference resolution (plaintext refused, scoped pools,
  loud denial of unauthorized references);
* outbound egress policy (undeclared origins refused before connecting,
  declared origins reachable through the guarded seam — proven against a real
  loopback socket, with bypass detection by wire evidence rather than text);
* tenant/workspace scope propagation onto persisted effect records;
* timeout/cancellation/error normalization onto the canonical Invocation
  ledger (FAILED is retryable, UNKNOWN preserves ambiguity, cancellation is
  recorded, deadlines actually cancel);
* usage/cost/provenance reporting (exactly-once recording, unreported markers,
  refusal of negative usage);
* direct model/tool/network bypass refusal before dispatch.

A subject opts in by implementing :class:`ConformanceSubject` (optionally via
the ``maistro.conformance`` entry-point group, which ``maistro conformance``
discovers). Built-in implementations use the same protocol — there is no
built-in fast path. Reports name the exact contract id, contract version, and
backend leg each claim rests on; a skipped check or a skipped required
real-backend leg (``MAISTRO_REQUIRE_REAL_BACKEND_LEGS``) never supports a
claim and is fatal under the require switch.
"""

from maistro.conformance.contract import (
    CONTRACT_ID,
    CONTRACT_VERSION,
    ENTRY_POINT_GROUP,
    ENV_REQUIRE_REAL_BACKENDS,
    MEMORY_BACKEND,
    BackendKind,
    BackendLeg,
    CheckId,
    CheckResult,
    CheckStatus,
    ConformanceFailure,
    ConformanceReport,
    SubjectDescriptor,
    SubjectFamily,
    require_real_backends_from_env,
    version_compatible,
)
from maistro.conformance.runner import (
    ConformanceRunner,
    assert_conformant,
    discover_subjects,
    render_report,
    run_conformance,
    run_registered_subjects,
)
from maistro.conformance.subject import (
    ConformanceSubject,
    EffectRequest,
)

__all__ = [
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "ENTRY_POINT_GROUP",
    "ENV_REQUIRE_REAL_BACKENDS",
    "MEMORY_BACKEND",
    "BackendKind",
    "BackendLeg",
    "CheckId",
    "CheckResult",
    "CheckStatus",
    "ConformanceFailure",
    "ConformanceReport",
    "ConformanceRunner",
    "ConformanceSubject",
    "EffectRequest",
    "SubjectDescriptor",
    "SubjectFamily",
    "assert_conformant",
    "discover_subjects",
    "render_report",
    "require_real_backends_from_env",
    "run_conformance",
    "run_registered_subjects",
    "version_compatible",
]
