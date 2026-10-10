"""The conformance runner: subject in, auditable report out (issue #965).

The runner owns everything the shared check bodies should not: outbound-policy
isolation for the egress legs, the local audit server that turns "did the
subject really use the guarded seam?" into a request count, the ordering of
checks, and the fatality rule for required real-backend legs.

Fatal skips: with ``MAISTRO_REQUIRE_REAL_BACKEND_LEGS`` set (or
``require_real_backends=True``), a required leg that cannot run — the audit
socket could not bind, the subject says its real backend is unavailable —
fails the whole run instead of passing with a documented skip. Without the
switch the skip is still recorded, and the report's ``claim_valid`` is false,
so a partial run can never be quoted as conformance.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from importlib import metadata
from typing import Any

from maistro.conformance.checks import (
    check_bypass_refused,
    check_cancellation_normalization,
    check_credential_ref_resolution,
    check_deadline_enforcement,
    check_egress,
    check_error_normalization,
    check_scope_propagation,
    check_secrets_plaintext_refused,
    check_usage_and_provenance,
    declare_egress_origin,
)
from maistro.conformance.contract import (
    CONTRACT_ID,
    CONTRACT_VERSION,
    BackendKind,
    BackendLeg,
    CheckId,
    CheckResult,
    CheckStatus,
    ConformanceFailure,
    ConformanceReport,
    SubjectDescriptor,
    require_real_backends_from_env,
)
from maistro.conformance.subject import ConformanceSubject
from maistro.security.outbound import (
    OutboundPolicy,
    configure_outbound_policy,
    current_outbound_policy,
    outbound_origin,
    reset_outbound_policy,
)

#: How long the runner waits for the audit server to accept its shutdown.
_AUDIT_DRAIN_SECONDS = 2.0


class _AuditServer:
    """A real loopback HTTP/1.1 socket that counts the requests it accepts.

    This is the real-backend leg's instrument. It is deliberately a raw
    ``asyncio`` server rather than a framework app: the only property under
    test is whether bytes arrived on the wire, which is exactly what a
    guarded-transport bypass would produce.
    """

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._hits = 0

    @property
    def port(self) -> int:
        server = self._server
        if server is None or not server.sockets:
            raise RuntimeError("audit server not started")
        return int(server.sockets[0].getsockname()[1])

    async def start(self) -> _AuditServer:
        # devskim: ignore DS137138 -- loopback-only fixture server on an
        # ephemeral port (0); lives only for the duration of this run.
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        return self

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        del reader
        self._hits += 1
        try:
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def hit_count(self) -> int:
        return self._hits

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._server.wait_closed(), timeout=_AUDIT_DRAIN_SECONDS)


def _restore_policy(saved: OutboundPolicy) -> None:
    """Restore the outbound policy the run found in force.

    The egress legs need a policy nobody else mutated under them, so the
    runner resets, probes, and then re-adds exactly the origins that were
    allowed before — additive semantics, matching production configuration.
    """
    reset_outbound_policy()
    configure_outbound_policy(*sorted(saved.origins))


async def _guarded(check_id: CheckId, probe: Coroutine[Any, Any, CheckResult]) -> CheckResult:
    """Await one check probe, demoting a crash to a FAIL result.

    A nonconforming subject may raise from ``resolve_provider``, ``execute``,
    or any other hook a probe calls. That defect belongs to the subject under
    test, so it is recorded as a failed check and the suite goes on; the run
    still produces a report covering the remaining checks. Cancellation and
    other ``BaseException`` s propagate: they mean the run itself is stopping,
    not that the probe failed.
    """
    try:
        return await probe
    except Exception as exc:
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.FAIL,
            detail=f"probe crashed: {type(exc).__name__}: {exc}",
        )


class ConformanceRunner:
    """Run the shared suite against one subject, producing one report."""

    def __init__(self, *, require_real_backends: bool | None = None) -> None:
        self._require_real_backends = (
            require_real_backends_from_env()
            if require_real_backends is None
            else require_real_backends
        )

    @property
    def require_real_backends(self) -> bool:
        return self._require_real_backends

    async def run(self, subject: ConformanceSubject) -> ConformanceReport:
        """Execute every contract check against ``subject``.

        A check body that raises records a FAIL with the exception as detail —
        a crash is a failed probe, not a skip. The egress legs run only when
        the real audit socket could bind; otherwise they record a skip, the
        report says the real backend never executed, and (when required) the
        caller is told the run is fatal.
        """
        descriptor = SubjectDescriptor(
            name=subject.descriptor.name,
            family=subject.descriptor.family,
            declared_contract_version=subject.descriptor.declared_contract_version,
        )
        results: list[CheckResult] = []
        saved_policy = current_outbound_policy()
        audit: _AuditServer | None = None
        backend = subject.backend
        real_backend_executed = False
        try:
            results.append(
                await _guarded(
                    CheckId.SECRETS_PLAINTEXT_REFUSED,
                    check_secrets_plaintext_refused(subject),
                )
            )
            results.append(
                await _guarded(
                    CheckId.SECRETS_CREDENTIAL_REF_RESOLUTION,
                    check_credential_ref_resolution(subject),
                )
            )
            results.append(
                await _guarded(CheckId.SCOPE_PROPAGATION, check_scope_propagation(subject))
            )
            results.append(
                await _guarded(CheckId.ERROR_NORMALIZATION, check_error_normalization(subject))
            )
            results.append(
                await _guarded(
                    CheckId.CANCELLATION_NORMALIZATION,
                    check_cancellation_normalization(subject),
                )
            )
            results.append(
                await _guarded(CheckId.DEADLINE_ENFORCEMENT, check_deadline_enforcement(subject))
            )
            results.append(
                await _guarded(CheckId.USAGE_AND_PROVENANCE, check_usage_and_provenance(subject))
            )

            if subject.real_backend_available():
                try:
                    audit = await _AuditServer().start()
                except OSError as exc:
                    results.append(
                        CheckResult(
                            check_id=CheckId.EGRESS_UNDECLARED_BLOCKED,
                            status=CheckStatus.SKIP,
                            detail=f"audit socket unavailable: {exc}",
                        )
                    )
                    results.append(
                        CheckResult(
                            check_id=CheckId.EGRESS_DECLARED_ALLOWED,
                            status=CheckStatus.SKIP,
                            detail=f"audit socket unavailable: {exc}",
                        )
                    )
                    backend = BackendLeg(
                        name="memory-only",
                        kind=BackendKind.MOCK,
                        detail="real-backend leg skipped: loopback bind refused",
                    )
            else:
                results.append(
                    CheckResult(
                        check_id=CheckId.EGRESS_UNDECLARED_BLOCKED,
                        status=CheckStatus.SKIP,
                        detail="subject reported its real backend unavailable",
                    )
                )
                results.append(
                    CheckResult(
                        check_id=CheckId.EGRESS_DECLARED_ALLOWED,
                        status=CheckStatus.SKIP,
                        detail="subject reported its real backend unavailable",
                    )
                )
            if audit is not None:
                # The run exercised a real socket: say so on the report's
                # backend instead of letting a real-backend run read as a
                # pure in-memory leg.
                backend = BackendLeg(
                    name=f"memory+{backend.name}",
                    kind=BackendKind.REAL,
                    detail="egress probes ran against a real loopback socket",
                )
                real_backend_executed = True
                # devskim: ignore DS137138 -- same loopback-only audit
                # fixture server as above; ephemeral, per-run lifetime.
                probe_url = f"http://127.0.0.1:{audit.port}/conformance-probe"
                results.append(
                    await _guarded(
                        CheckId.EGRESS_UNDECLARED_BLOCKED,
                        check_egress(
                            subject,
                            probe_url=probe_url,
                            audit_server=audit,
                            allow_origin=False,
                        ),
                    )
                )
                declare_egress_origin(outbound_origin(probe_url))
                results.append(
                    await _guarded(
                        CheckId.EGRESS_DECLARED_ALLOWED,
                        check_egress(
                            subject,
                            probe_url=probe_url,
                            audit_server=audit,
                            allow_origin=True,
                        ),
                    )
                )
                results.append(
                    await _guarded(
                        CheckId.BYPASS_REFUSED,
                        check_bypass_refused(subject, audit_server=audit),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_id=CheckId.BYPASS_REFUSED,
                        status=CheckStatus.SKIP,
                        detail="bypass probe requires the real-backend egress leg",
                    )
                )
        finally:
            _restore_policy(saved_policy)
            if audit is not None:
                await audit.stop()
        report = ConformanceReport(
            descriptor=descriptor,
            backend=backend,
            results=results,
            contract_id=CONTRACT_ID,
            contract_version=CONTRACT_VERSION,
            real_backend_executed=real_backend_executed,
        )
        return report

    def fatal_skip(self, report: ConformanceReport) -> str | None:
        """The reason a report is fatal under the require-real-backends rule.

        Returns None when nothing fatal applies: either the rule is off, or
        every required real-backend check actually executed (pass or fail —
        a genuine failure is a conformance finding, not a missing leg).
        """
        if not self._require_real_backends:
            return None
        missing = [
            entry
            for entry in report.results
            if entry.status is CheckStatus.SKIP
            and entry.check_id
            in (
                CheckId.EGRESS_UNDECLARED_BLOCKED,
                CheckId.EGRESS_DECLARED_ALLOWED,
                CheckId.BYPASS_REFUSED,
            )
        ]
        if not missing:
            return None
        names = ", ".join(sorted({entry.check_id.value for entry in missing}))
        return (
            f"required real-backend leg(s) skipped for subject {report.descriptor.name!r}: {names}"
        )


async def run_conformance(
    subject: ConformanceSubject, *, require_real_backends: bool | None = None
) -> ConformanceReport:
    """Run the shared suite against one subject (convenience wrapper)."""
    return await ConformanceRunner(require_real_backends=require_real_backends).run(subject)


def assert_conformant(reports: list[ConformanceReport]) -> None:
    """Raise unless every report supports a valid conformance claim.

    This is where "skipped required real-backend legs are fatal" lands: a run
    under ``MAISTRO_REQUIRE_REAL_BACKEND_LEGS`` that contains a skipped leg
    raises with the skipped check names, and a report whose claim is invalid
    (any FAIL/SKIP, version mismatch) raises with the specifics.
    """
    problems: list[str] = []
    runner = ConformanceRunner(require_real_backends=require_real_backends_from_env())
    for report in reports:
        fatal = runner.fatal_skip(report)
        if fatal:
            problems.append(fatal)
        elif not report.claim_valid:
            failed = ", ".join(
                f"{entry.check_id.value}={entry.status.value}"
                for entry in (*report.failures, *report.skipped)
            )
            problems.append(
                f"subject {report.descriptor.name!r} does not support a conformance "
                f"claim (declared contract {report.descriptor.declared_contract_version}, "
                f"tested {report.contract_version}): {failed or 'no checks recorded'}"
            )
    if problems:
        raise ConformanceFailure("; ".join(problems))


def discover_subjects(group: str = "maistro.conformance") -> list[ConformanceSubject]:
    """Load every subject registered under the conformance entry-point group.

    Third-party (and built-in) implementations opt in by declaring an entry
    point whose factory returns a :class:`ConformanceSubject`. Registration is
    the only mechanism — there is no name-based fallback that could silently
    run against the wrong implementation.
    """
    subjects: list[ConformanceSubject] = []
    for entry in metadata.entry_points(group=group):
        factory = entry.load()
        subject = factory()
        if not isinstance(subject, ConformanceSubject):
            raise ConformanceFailure(
                f"entry point {entry.name!r} in group {group!r} did not produce a "
                "ConformanceSubject"
            )
        subjects.append(subject)
    return subjects


def render_report(report: ConformanceReport) -> str:
    """Render one report as operator-readable text (the CLI surface)."""
    lines = [
        f"subject: {report.descriptor.name}",
        f"family: {report.descriptor.family.value}",
        f"contract: {report.contract_id} @ {report.contract_version} "
        f"(subject declared {report.descriptor.declared_contract_version})",
        f"backend: {report.backend.name} [{report.backend.kind.value}] {report.backend.detail}".rstrip(),
        f"real backend executed: {report.real_backend_executed}",
        f"claim valid: {report.claim_valid}",
        f"conforms: {report.conforms}",
    ]
    for entry in report.results:
        marker = {CheckStatus.PASS: "PASS", CheckStatus.FAIL: "FAIL", CheckStatus.SKIP: "SKIP"}[
            entry.status
        ]
        lines.append(f"  [{marker}] {entry.check_id.value}: {entry.detail}")
    return "\n".join(lines)


async def run_registered_subjects(group: str = "maistro.conformance") -> list[ConformanceReport]:
    """Run every registered subject and enforce the fatal contract.

    Returns the reports only when every subject supports a valid conformance
    claim; otherwise raises :class:`ConformanceFailure` (which also carries the
    skipped-required-leg rule under ``MAISTRO_REQUIRE_REAL_BACKEND_LEGS``).
    """
    subjects = discover_subjects(group)
    if not subjects:
        raise ConformanceFailure(
            f"no conformance subjects registered under entry-point group {group!r}"
        )
    reports = [await ConformanceRunner().run(subject) for subject in subjects]
    assert_conformant(reports)
    return reports


__all__ = [
    "ConformanceRunner",
    "assert_conformant",
    "discover_subjects",
    "render_report",
    "run_conformance",
    "run_registered_subjects",
]
