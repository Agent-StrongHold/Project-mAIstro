"""Pre-publication extension certification: validate, sign, report truthfully
(M9-H3, #975).

This module is the supported pre-publication workflow the M9-H epic names:
it validates an extension package's structure, runs the declared
manifest / public-import / security / conformance checks, signs the result,
and emits a report that says *exactly* what was proven — never more.

The truthfulness contract (the issue's acceptance criteria, made structural):

- A check answers with one of four outcomes: ``passed``, ``failed``,
  ``skipped`` or ``not_applicable``. Only ``passed`` and ``failed`` are
  *executed* outcomes. A check earns claims only by executing and passing:
  :attr:`CheckResult.earned_claims` collapses to nothing for skipped,
  not-applicable and failed checks, so a report structurally cannot claim a
  property whose test did not execute.
- A :class:`CertificationProfile` names the checks a certification
  *requires*. A required check that was skipped, answered not-applicable, or
  never ran at all refuses certification. Nothing else does: skipped
  *optional* checks are recorded truthfully and prove nothing, but they do
  not block.
- The signed artifact is the report digest, and the report carries the digest
  of the exact certified package bytes (:meth:`ExtensionBundle.digest`). The
  signature therefore corresponds to those bytes and nothing else; presenting
  different bytes to :func:`verify_certified_package` or
  :func:`certification_as_trust_claim` fails closed. A later mutation of the
  package cannot ride on an old certification.
- The report records the extension identity (id, version, publisher, API
  contract version), the exact manifest/artifact/package digests, and the
  full test environment: SDK and certifier versions, host, backend, Python
  and platform, execution time.
- Certification is *evidence*, never authorization. The install lifecycle
  consumes it through :func:`certification_as_trust_claim`, which feeds the
  governed inspect step's trust evaluation — and the machine still requires
  the explicit operator decision before anything activates.

No function here imports or executes extension code. The import and security
checks are static AST scans over the packaged source bytes; conformance
suites are host-supplied objects the orchestrator invokes and records —
their outcomes count as executed evidence because the orchestrator actually
called them and recorded what came back.
"""

from __future__ import annotations

import ast
import json
import platform as _platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib import metadata
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature as _InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from maistro.extensions.manifest import (
    inspect_manifest,
    sha256_hex,
    verify_package_payload,
)
from maistro.extensions.types import ExtensionManifest, ManifestRejected, TrustClaim

#: Version tag of the certification report document itself. Old reports can
#: never be re-read as a new format; the digest a seal covers includes this.
CERTIFICATION_FORMAT = "maistro-extension-certification:v1"

#: Version tag of the seal envelope wrapped around a report digest.
SEAL_FORMAT = "maistro-extension-certification-seal:v1"

#: Version of the certifier implementation that produced a report. Bumped
#: when check semantics change, independently of the package version.
CERTIFIER_VERSION = "1.0.0"

#: Framing tag hashed into the certified package bytes, so a bundle digest can
#: never be confused with a digest of some other concatenation.
BUNDLE_FORMAT = "maistro-extension-bundle:v1"

#: Check ids of the built-in checks. Profiles and CI wiring refer to checks by
#: these ids; the ids are part of the report contract.
STRUCTURE_CHECK_ID = "structure"
ENTRYPOINTS_CHECK_ID = "entrypoints"
PUBLIC_IMPORTS_CHECK_ID = "public-imports"
SECURITY_SCAN_CHECK_ID = "security-scan"
CONFORMANCE_CHECK_ID = "conformance"


class CertificationError(RuntimeError):
    """Base class for certification workflow failures."""


class CertificationInvalid(CertificationError):
    """A report or seal cannot be trusted as presented.

    Raised on format mismatches, digest or signature failures, reports whose
    stored status disagrees with their own recorded results, and attempts to
    mint evidence from a certification that did not pass.
    """


class CertificationPackageMismatch(CertificationError):
    """The bytes presented are not the bytes the certification describes.

    The association between a certification and a package is its digest. A
    package mutated after certification fails here, and the failure names
    which layer (package, manifest or artifact) no longer matches.
    """


class DuplicateCheckError(CertificationError):
    """Two checks in one certification run share a check id."""


class UnboundCheckError(CertificationError):
    """A bundle-bound check was built for a bundle other than the certified one.

    Checks that execute against package bytes capture their bundle at
    construction. Certification refuses to run such a check against a
    different bundle than the one whose digests the report will describe,
    so the evidence in the report can only come from the certified bytes.
    """


class CheckOutcome(StrEnum):
    """The four truthful answers a check can give.

    ``passed`` and ``failed`` are executed outcomes — the check ran and
    produced a verdict. ``skipped`` means the check declined to run (nothing
    to run was supplied); ``not_applicable`` means the check has no subject
    in this package (for example an import scan over a package with no
    source files). Neither is execution, and neither can earn a claim.
    """

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


#: Outcomes that mean the check actually executed.
_EXECUTED_OUTCOMES = frozenset({CheckOutcome.PASSED, CheckOutcome.FAILED})


@dataclass(frozen=True)
class CheckResult:
    """One check's truthful answer.

    ``claims`` lists the properties this check *would* prove by passing —
    they are the check's own declaration, fixed at construction. The report
    only counts them as earned when the outcome is ``passed``; a failed,
    skipped or not-applicable check earns nothing.
    """

    check_id: str
    title: str
    outcome: CheckOutcome
    detail: str
    claims: tuple[str, ...] = ()

    @property
    def executed(self) -> bool:
        """Whether the check ran and produced a real verdict."""
        return self.outcome in _EXECUTED_OUTCOMES

    @property
    def earned_claims(self) -> tuple[str, ...]:
        """The claims this result actually proves: only a pass earns them."""
        return self.claims if self.outcome is CheckOutcome.PASSED else ()


class CertificationCheck(Protocol):
    """One certifiable check: an id, a title, and a run that answers once.

    Implementations capture everything they need at construction (package
    bytes, policy, suites); :meth:`run` executes and returns the answer. A
    check runs at most once per certification, and a check that raises has a
    bug: orchestration does not catch its exceptions, because an unanswerable
    run must stop certification rather than invent an outcome.
    """

    check_id: str
    title: str

    def run(self) -> CheckResult: ...


#: Checks that execute against a specific :class:`ExtensionBundle` expose it
#: through a ``bound_bundle`` attribute; :func:`certify` refuses a run in
#: which such a check is bound to any bundle but the one being certified.


@dataclass(frozen=True)
class CertificationProfile:
    """A named set of checks a certification requires.

    ``required_checks`` names check ids that must *execute and pass* for the
    certification to succeed. A required check that is skipped, answers
    not-applicable, or is missing from the run entirely refuses
    certification. Checks outside the required set are recorded truthfully
    and may earn claims when they pass, but their absence or skip is not
    itself disqualifying.
    """

    name: str
    required_checks: tuple[str, ...]


#: The minimal profile: manifest and artifact evidence only. Sufficient to
#: state "this manifest is well-formed and binds these bytes" — and nothing
#: else; the report's claim list makes the gap explicit.
MANIFEST_PROFILE = CertificationProfile(name="manifest", required_checks=(STRUCTURE_CHECK_ID,))

#: The pre-publication profile: everything a package must prove before it may
#: be published — structure, shipped entry points, public-SDK-only imports,
#: a clean dynamic-execution scan, and executed conformance suites. A suite
#: that was never declared is a skipped required check and refuses
#: certification, exactly as the acceptance criteria demand.
PUBLICATION_PROFILE = CertificationProfile(
    name="publication",
    required_checks=(
        STRUCTURE_CHECK_ID,
        ENTRYPOINTS_CHECK_ID,
        PUBLIC_IMPORTS_CHECK_ID,
        SECURITY_SCAN_CHECK_ID,
        CONFORMANCE_CHECK_ID,
    ),
)


@dataclass(frozen=True)
class ExtensionBundle:
    """The exact bytes under certification.

    ``manifest_bytes`` and ``payload`` are the candidate's manifest and its
    declared artifact. ``sources`` optionally carries the packaged source
    files as ``(path, bytes)`` pairs — the material the static import and
    security scans read. The certified package digest is taken over all of
    it, framed, so the certification covers exactly these bytes.
    """

    manifest_bytes: bytes
    payload: bytes
    sources: tuple[tuple[str, bytes], ...] = ()

    def framed_bytes(self) -> bytes:
        """The canonical byte serialization this certification covers.

        Length-prefixed, tag-led, sources in sorted path order: two bundles
        digest equal only when every part is byte-identical.
        """
        parts: list[bytes] = [BUNDLE_FORMAT.encode(), self.manifest_bytes, self.payload]
        for path, data in sorted(self.sources):
            parts.append(path.encode())
            parts.append(data)
        framed = bytearray()
        for part in parts:
            framed += len(part).to_bytes(8, "big")
            framed += part
        return bytes(framed)

    def digest(self) -> str:
        """SHA-256 over :meth:`framed_bytes` — the certified package digest."""
        return sha256_hex(self.framed_bytes())


def bundle_digest(bundle: ExtensionBundle) -> str:
    """The certified package digest of ``bundle`` (convenience wrapper)."""
    return bundle.digest()


@dataclass(frozen=True)
class CertificationEnvironment:
    """Where and with what the certification checks executed.

    Every field is recorded, never inferred later: a report says which SDK
    and certifier versions ran, on which host and backend, under which
    Python and platform, at which instant. Tests pin these values by
    constructing the record directly instead of calling
    :func:`detect_environment`.
    """

    sdk_name: str
    sdk_version: str
    certifier_version: str
    host: str
    backend: str
    python_version: str
    platform: str
    executed_at: datetime


def detect_environment(*, backend: str = "local") -> CertificationEnvironment:
    """The real environment of this process, recorded at certification time."""
    return CertificationEnvironment(
        sdk_name="maistro-core",
        sdk_version=_distribution_version("maistro-core"),
        certifier_version=CERTIFIER_VERSION,
        host=_platform.node(),
        backend=backend,
        python_version=sys.version.split()[0],
        platform=_platform.platform(),
        executed_at=datetime.now(UTC),
    )


def _distribution_version(distribution: str) -> str:
    """Installed version of ``distribution``, or ``"unknown"`` unbuilt."""
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:  # pragma: no cover - only unbuilt checkouts
        return "unknown"


@dataclass(frozen=True)
class CertificationSubject:
    """What was certified: the extension identity and its exact digests.

    ``package_sha256`` covers the whole framed bundle — the bytes a seal
    answers for. ``manifest_sha256`` and ``artifact_sha256`` anchor the
    individual parts, so a mismatch names its layer. When the manifest bytes
    cannot even be parsed, the identity fields are empty and the digests
    still record what was presented: the report remains truthful about an
    unidentifiable candidate.
    """

    extension_id: str
    version: str
    publisher: str
    api_version: str
    manifest_sha256: str
    artifact_sha256: str
    artifact_size: int
    package_sha256: str


@dataclass(frozen=True)
class CertificationReport:
    """The durable answer to "what was proven about this package".

    ``certified`` and ``refusals`` are computed once, at certification time,
    from the recorded results and the profile's requirements — and
    re-verified against the same derivation on every load
    (:func:`report_from_json`) and every verification
    (:func:`verify_certification`), so a hand-edited status field is
    refuseable even before a seal is consulted. ``certified_claims`` is
    derived, never stored: it is exactly the claims of results that executed
    and passed.
    """

    format_version: str
    profile: str
    required_checks: tuple[str, ...]
    subject: CertificationSubject
    environment: CertificationEnvironment
    results: tuple[CheckResult, ...]
    certified: bool
    refusals: tuple[str, ...]

    @property
    def certified_claims(self) -> tuple[str, ...]:
        """Every property proven by an executed, passing check — no more."""
        earned: set[str] = set()
        for result in self.results:
            earned.update(result.earned_claims)
        return tuple(sorted(earned))


def _evaluate(
    results: Sequence[CheckResult], required_checks: tuple[str, ...]
) -> tuple[bool, tuple[str, ...]]:
    """The certification decision: ``(certified, refusals)`` for these results.

    Three refusal causes, each named explicitly: a required check that never
    ran, a required check that did not pass, and any check that failed. A
    skipped or not-applicable *optional* check is neither.
    """
    by_id = {result.check_id: result for result in results}
    refusals: list[str] = []
    for required in required_checks:
        result = by_id.get(required)
        if result is None:
            refusals.append(f"required check {required!r} never ran")
        elif result.outcome is not CheckOutcome.PASSED:
            refusals.append(
                f"required check {required!r} did not pass (outcome: {result.outcome.value})"
            )
    for result in results:
        if result.outcome is CheckOutcome.FAILED:
            refusals.append(f"check {result.check_id!r} failed: {result.detail}")
    return (not refusals, tuple(refusals))


def _report_status(report: CertificationReport) -> tuple[bool, tuple[str, ...]]:
    """Recompute a report's decision from its own recorded fields."""
    return _evaluate(report.results, report.required_checks)


# ---------------------------------------------------------------------------
# Built-in checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ParsedManifest:
    """The parsed manifest plus the outcome of parsing it.

    Certification must stay truthful when the manifest cannot parse at all:
    the structure check answers ``failed`` and the report's subject digests
    still record what was presented. Nothing downstream re-parses.
    """

    manifest: ExtensionManifest | None
    rejected: str | None


def _parse_for_certification(manifest_bytes: bytes) -> _ParsedManifest:
    """Parse manifest bytes once per check run, refusing nothing silently."""
    try:
        return _ParsedManifest(manifest=inspect_manifest(manifest_bytes), rejected=None)
    except ManifestRejected as exc:
        return _ParsedManifest(manifest=None, rejected=str(exc))


class PackageStructureCheck:
    """Manifest well-formedness and the artifact binding it claims.

    The foundation of "the signed digest corresponds exactly to the
    certified package bytes": this check is where the manifest's artifact
    claim is verified against the payload bytes, so the report's artifact
    digest is a verified fact rather than a copied string.
    """

    check_id = STRUCTURE_CHECK_ID
    title = "Package structure: manifest well-formed, artifact bound"

    def __init__(self, bundle: ExtensionBundle) -> None:
        self._bundle = bundle

    @property
    def bound_bundle(self) -> ExtensionBundle:
        """The bundle this check executes against (binding validation)."""
        return self._bundle

    def run(self) -> CheckResult:
        parsed = _parse_for_certification(self._bundle.manifest_bytes)
        if parsed.manifest is None:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.FAILED,
                detail=parsed.rejected or "manifest unparseable",
            )
        try:
            verify_package_payload(parsed.manifest, self._bundle.payload)
        except ManifestRejected as exc:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.FAILED,
                detail=str(exc),
            )
        return CheckResult(
            check_id=self.check_id,
            title=self.title,
            outcome=CheckOutcome.PASSED,
            detail=(
                f"manifest valid for {parsed.manifest.extension_id} "
                f"{parsed.manifest.version}; artifact digest and size verified"
            ),
            claims=("package.manifest-valid", "package.artifact-bound"),
        )


def _module_file_candidates(module: str) -> frozenset[str]:
    """Archive paths a dotted module name may legally live at."""
    parts = module.split(".")
    return frozenset(
        {
            "/".join([*parts, "__init__.py"]),
            "/".join([*parts[:-1], f"{parts[-1]}.py"]),
        }
    )


class EntryPointPresenceCheck:
    """Every declared entry point's module must ship in the package.

    A manifest naming ``acme.plugin`` whose module file is absent from the
    packaged sources installs into a host that cannot load it — or worse,
    resolves the name against something that is not the extension's own
    code. This check runs over the packaged source set; with no sources
    supplied there is nothing to contain, and the answer is truthfully
    ``not_applicable``.
    """

    check_id = ENTRYPOINTS_CHECK_ID
    title = "Entry-point modules present in packaged sources"

    def __init__(self, bundle: ExtensionBundle) -> None:
        self._bundle = bundle

    @property
    def bound_bundle(self) -> ExtensionBundle:
        """The bundle this check executes against (binding validation)."""
        return self._bundle

    def run(self) -> CheckResult:
        parsed = _parse_for_certification(self._bundle.manifest_bytes)
        if parsed.manifest is None:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.FAILED,
                detail=f"manifest unparseable, entry points unknowable: {parsed.rejected}",
            )
        if not self._bundle.sources:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.NOT_APPLICABLE,
                detail="no packaged sources supplied; entry-point containment not checked",
            )
        paths = {path for path, _ in self._bundle.sources}
        missing = [
            f"{point.name}: {point.module}"
            for point in parsed.manifest.entry_points
            if _module_file_candidates(point.module).isdisjoint(paths)
        ]
        if missing:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.FAILED,
                detail="entry-point modules absent from packaged sources: " + "; ".join(missing),
            )
        return CheckResult(
            check_id=self.check_id,
            title=self.title,
            outcome=CheckOutcome.PASSED,
            detail=f"{len(parsed.manifest.entry_points)} entry point(s) present in sources",
            claims=("package.entrypoints-shipped",),
        )


@dataclass(frozen=True)
class ImportPolicy:
    """The public/private namespace boundary a package's imports must respect.

    ``public_namespaces`` are the first-party roots an extension may import;
    ``private_namespaces`` are first-party roots it must never import; the
    repo-relative roots are checkout-layout imports, forbidden outright.
    Underscore-prefixed submodules under a public root stay private — the
    same rule ``scripts/check-extension-imports.py`` enforces for the
    repository's own trees, applied here to one candidate package's shipped
    bytes at certification time.
    """

    public_namespaces: frozenset[str]
    private_namespaces: frozenset[str] = frozenset()
    repo_relative_roots: frozenset[str] = frozenset({"packages", "extensions"})


def _forbidden_root(dotted: str, policy: ImportPolicy) -> str | None:
    """Why importing ``dotted`` violates the policy, or ``None`` if allowed."""
    root = dotted.split(".")[0]
    if root in policy.repo_relative_roots:
        return "repo-relative import of the checkout layout"
    if root in policy.private_namespaces:
        return "product-private import"
    submodules = dotted.split(".")[1:]
    if root in policy.public_namespaces and any(part.startswith("_") for part in submodules):
        return "underscore-private module under a public root"
    return None


class PublicImportCheck:
    """Static public-SDK-only import scan over the packaged sources.

    Reads bytes with :mod:`ast` and imports nothing. Violations: importing a
    product-private root, importing a repo-relative root, reaching an
    underscore-private module under a public root (both import spellings),
    mutating ``sys.path`` to repair for a checkout layout, and dynamic
    imports on a string literal that names any of the above. Relative
    imports inside the package and the standard library are fine.
    """

    check_id = PUBLIC_IMPORTS_CHECK_ID
    title = "Public-import policy: shipped sources import only public namespaces"

    def __init__(self, bundle: ExtensionBundle, policy: ImportPolicy) -> None:
        self._bundle = bundle
        self._policy = policy

    @property
    def bound_bundle(self) -> ExtensionBundle:
        """The bundle this check executes against (binding validation)."""
        return self._bundle

    def run(self) -> CheckResult:
        if not self._bundle.sources:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.NOT_APPLICABLE,
                detail="no packaged sources supplied; import policy not checked",
            )
        violations: list[str] = []
        for path, data in sorted(self._bundle.sources):
            violations.extend(_scan_imports(path, data, self._policy))
        if violations:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.FAILED,
                detail="; ".join(violations),
            )
        return CheckResult(
            check_id=self.check_id,
            title=self.title,
            outcome=CheckOutcome.PASSED,
            detail=f"{len(self._bundle.sources)} source file(s) scanned, no violations",
            claims=("imports.public-sdk-only",),
        )


def _parse_source(path: str, data: bytes) -> ast.Module | None:
    """Parse packaged source bytes; unparseable bytes scan to a named gap.

    A file that does not compile fails the build elsewhere; these scans only
    claim what they actually read, so a syntax error surfaces as a finding
    naming the file instead of a silent pass.
    """
    try:
        return ast.parse(data.decode("utf-8"), filename=path)
    except (SyntaxError, UnicodeDecodeError):
        return None


def _scan_import_node(
    path: str, node: ast.stmt | ast.Call, policy: ImportPolicy, aliases: frozenset[str]
) -> list[str]:
    """Violations one AST node contributes, dispatched by node kind."""
    if isinstance(node, ast.Import):
        return [
            f"{path}:{node.lineno}: import {alias.name} — {reason}"
            for alias in node.names
            if (reason := _forbidden_root(alias.name, policy)) is not None
        ]
    if isinstance(node, ast.ImportFrom):
        return _scan_import_from(path, node, policy)
    if isinstance(node, ast.Call):
        return [
            *_scan_dynamic_import_call(path, node, policy, aliases),
            *_scan_sys_path_call(path, node),
        ]
    return []


def _scan_import_from(path: str, node: ast.ImportFrom, policy: ImportPolicy) -> list[str]:
    """Violations of one ``from … import …`` statement."""
    if node.level > 0:
        return []  # relative import inside the package's own tree
    module = node.module or ""
    if reason := _forbidden_root(module, policy):
        return [f"{path}:{node.lineno}: from {module} import … — {reason}"]
    if module.split(".")[0] not in policy.public_namespaces:
        return []
    private = [alias.name for alias in node.names if alias.name.startswith("_")]
    if not private:
        return []
    return [
        f"{path}:{node.lineno}: from {module} import {', '.join(private)} — "
        "underscore-private member under a public root"
    ]


def _scan_imports(path: str, data: bytes, policy: ImportPolicy) -> list[str]:
    """Violations of the import policy in one source file."""
    tree = _parse_source(path, data)
    if tree is None:
        return [f"{path}: source not parseable; import policy scan skipped for this file"]
    violations: list[str] = []
    aliases = _dynamic_import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Call)):
            violations.extend(_scan_import_node(path, node, policy, aliases))
    return violations


def _dynamic_import_aliases(tree: ast.Module) -> frozenset[str]:
    """Alias spellings bound to importlib's dynamic-import functions.

    ``from importlib import import_module as load`` re-binds the loader under
    a name the call-site spelling check cannot recognize on its own; every
    scanned file contributes its aliases and the scanners match calls against
    the canonical names plus these. Module aliases (``import importlib as
    il``) need no tracking — the attribute's final segment already spells
    ``import_module``. Untracked rebinding through plain assignment remains
    outside what the scans claim to see.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").split(".")[0] == "importlib"
        ):
            aliases.update(
                alias.asname
                for alias in node.names
                if alias.asname and alias.name in {"__import__", "import_module"}
            )
    return frozenset(aliases)


def _called_name(func: ast.expr) -> str:
    """The bare or attribute name a call is made through."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _scan_dynamic_import_call(
    path: str, node: ast.Call, policy: ImportPolicy, aliases: frozenset[str]
) -> list[str]:
    """Literal-argument dynamic imports that name a forbidden root."""
    if _called_name(node.func) not in {"__import__", "import_module"} | aliases:
        return []
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return []  # non-literal dynamic imports are the security scan's finding
    target = node.args[0].value
    if not isinstance(target, str):
        return []
    if reason := _forbidden_root(target, policy):
        return [f"{path}:{node.lineno}: dynamic import of {target!r} — {reason}"]
    return []


def _scan_sys_path_call(path: str, node: ast.Call) -> list[str]:
    """``sys.path`` mutations that repair for a checkout layout."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in {"insert", "append", "extend"}):
        return []
    receiver = func.value
    if (
        isinstance(receiver, ast.Attribute)
        and receiver.attr == "path"
        and isinstance(receiver.value, ast.Name)
        and receiver.value.id == "sys"
    ):
        return [f"{path}:{node.lineno}: sys.path.{func.attr}() repairs for a checkout layout"]
    return []


class SecurityScanCheck:
    """Static dynamic-execution scan over the packaged sources.

    Flags the constructs a static scan *can* answer for: calls to ``eval``
    and ``exec``, and dynamic (non-literal) ``__import__`` /
    ``importlib.import_module`` calls — under aliases too — which the
    literal-target rules of :class:`PublicImportCheck` cannot see through. It claims exactly what it
    is — no dynamic code execution found in these bytes — and nothing
    broader; "the package is secure" is not a claim any static scan earns.
    """

    check_id = SECURITY_SCAN_CHECK_ID
    title = "Security scan: no dynamic code execution in shipped sources"

    def __init__(self, bundle: ExtensionBundle) -> None:
        self._bundle = bundle

    @property
    def bound_bundle(self) -> ExtensionBundle:
        """The bundle this check executes against (binding validation)."""
        return self._bundle

    def run(self) -> CheckResult:
        if not self._bundle.sources:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.NOT_APPLICABLE,
                detail="no packaged sources supplied; dynamic-execution scan not run",
            )
        findings: list[str] = []
        for path, data in sorted(self._bundle.sources):
            findings.extend(_scan_dynamic_execution(path, data))
        if findings:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.FAILED,
                detail="; ".join(findings),
            )
        return CheckResult(
            check_id=self.check_id,
            title=self.title,
            outcome=CheckOutcome.PASSED,
            detail=f"{len(self._bundle.sources)} source file(s) scanned, no dynamic execution",
            claims=("static.no-dynamic-execution",),
        )


def _scan_dynamic_execution(path: str, data: bytes) -> list[str]:
    """Dynamic-execution findings in one source file."""
    tree = _parse_source(path, data)
    if tree is None:
        return [f"{path}: source not parseable; dynamic-execution scan skipped for this file"]
    aliases = _dynamic_import_aliases(tree)
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        if name in {"eval", "exec"}:
            findings.append(f"{path}:{node.lineno}: call to {name}()")
        elif name in {"__import__", "import_module"} | aliases:
            literal_argument = bool(node.args) and isinstance(node.args[0], ast.Constant)
            if not literal_argument:
                findings.append(f"{path}:{node.lineno}: dynamic {name}() on a non-literal argument")
    return findings


@dataclass(frozen=True)
class ConformanceOutcome:
    """What one conformance suite reported after actually running."""

    suite_id: str
    passed: bool
    detail: str
    capabilities: tuple[str, ...] = ()


class ConformanceSuite(Protocol):
    """A host-supplied conformance suite the orchestrator executes.

    The suite runs extension code under the host's own harness (that is the
    M9-H2 runner's job); the certifier only invokes it and records what came
    back. A suite that raises has failed — the orchestrator converts the
    exception into a failed outcome rather than letting a crash decide the
    certification's shape.
    """

    suite_id: str

    def run(self) -> ConformanceOutcome: ...


class ConformanceCheck:
    """Orchestrates declared conformance suites and derives claims from runs.

    This is the conformance-execution seam of the certification workflow:
    hosts contribute suites (their own harnesses, or the shared family
    runners), the orchestrator executes each exactly once, and claims are
    minted per suite and per tested capability — only for suites that ran
    and passed. With no suites declared the answer is ``skipped``: nothing
    executed, so nothing is proven, and a profile that requires conformance
    refuses certification.
    """

    check_id = CONFORMANCE_CHECK_ID
    title = "Conformance suites executed against the package"

    def __init__(self, suites: Sequence[ConformanceSuite]) -> None:
        self._suites = list(suites)

    def run(self) -> CheckResult:
        if not self._suites:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.SKIPPED,
                detail="no conformance suites declared; nothing executed",
            )
        outcomes = [_execute_suite(suite) for suite in self._suites]
        claims: list[str] = []
        for outcome in outcomes:
            if not outcome.passed:
                continue
            claims.append(f"conformance.{outcome.suite_id}")
            claims.extend(f"capability.{cap}" for cap in outcome.capabilities)
        failures = [f"{o.suite_id}: {o.detail}" for o in outcomes if not o.passed]
        if failures:
            return CheckResult(
                check_id=self.check_id,
                title=self.title,
                outcome=CheckOutcome.FAILED,
                detail="failed suites: " + "; ".join(failures),
            )
        return CheckResult(
            check_id=self.check_id,
            title=self.title,
            outcome=CheckOutcome.PASSED,
            detail=f"{len(outcomes)} suite(s) executed and passed",
            claims=tuple(claims),
        )


def _execute_suite(suite: ConformanceSuite) -> ConformanceOutcome:
    """Run one suite, converting a crash into a truthful failed outcome."""
    try:
        return suite.run()
    except Exception as exc:
        return ConformanceOutcome(
            suite_id=suite.suite_id,
            passed=False,
            detail=f"suite raised {type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Certification run
# ---------------------------------------------------------------------------


def certify(
    bundle: ExtensionBundle,
    *,
    profile: CertificationProfile,
    environment: CertificationEnvironment,
    checks: Sequence[CertificationCheck],
    signer: Ed25519PrivateKey | None = None,
) -> tuple[CertificationReport, CertificationSeal]:
    """Run ``checks`` over ``bundle`` and emit the truthful report and seal.

    The report is produced whether or not the package passes: a failed
    certification with named refusals is exactly as worth emitting as a
    passing one. ``signer`` optionally seals the report digest with an
    Ed25519 key; the seal covers the report, whose digests cover the exact
    bundle bytes.
    """
    if len({check.check_id for check in checks}) != len(checks):
        raise DuplicateCheckError("a certification run received two checks with the same id")
    for check in checks:
        bound = getattr(check, "bound_bundle", None)
        if bound is not None and bound.digest() != bundle.digest():
            raise UnboundCheckError(
                f"check {check.check_id!r} was constructed for a different bundle "
                f"than the one being certified (bound {bound.digest()}, "
                f"certified {bundle.digest()})"
            )

    results = tuple(check.run() for check in checks)
    certified, refusals = _evaluate(results, profile.required_checks)
    parsed = _parse_for_certification(bundle.manifest_bytes)
    manifest = parsed.manifest
    subject = CertificationSubject(
        extension_id=manifest.extension_id if manifest else "",
        version=manifest.version if manifest else "",
        publisher=manifest.publisher if manifest else "",
        api_version=manifest.api_version if manifest else "",
        manifest_sha256=sha256_hex(bundle.manifest_bytes),
        artifact_sha256=sha256_hex(bundle.payload),
        artifact_size=len(bundle.payload),
        package_sha256=bundle.digest(),
    )
    report = CertificationReport(
        format_version=CERTIFICATION_FORMAT,
        profile=profile.name,
        required_checks=profile.required_checks,
        subject=subject,
        environment=environment,
        results=results,
        certified=certified,
        refusals=refusals,
    )
    seal = sign_certification(report, signer) if signer is not None else _unsigned_seal(report)
    return report, seal


# ---------------------------------------------------------------------------
# Sealing: digests, signatures, verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CertificationSeal:
    """An Ed25519 signature over one report's digest.

    The signer's public key travels in the seal so a report is verifiable
    without a key-distribution step; *trusting* that key is the consumer's
    decision, supplied to :func:`verify_certification` as the trusted key.
    An unsigned certification carries a seal with an empty signature and
    verifies as well-formed but proves no publisher origin.
    """

    format_version: str
    report_sha256: str
    signer_public_key: str
    signer_key_fingerprint: str
    signature: str
    sealed_at: datetime

    @property
    def signed(self) -> bool:
        """Whether a real signature is present."""
        return bool(self.signature)


def sign_certification(report: CertificationReport, signer: Ed25519PrivateKey) -> CertificationSeal:
    """Seal ``report`` with ``signer``: a signature over the report digest."""
    raw = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_hex = raw.hex()
    return CertificationSeal(
        format_version=SEAL_FORMAT,
        report_sha256=report_digest(report),
        signer_public_key=public_hex,
        signer_key_fingerprint=sha256_hex(bytes.fromhex(public_hex)),
        signature=signer.sign(_seal_payload(report)).hex(),
        sealed_at=datetime.now(UTC),
    )


def _unsigned_seal(report: CertificationReport) -> CertificationSeal:
    """The truthful seal of an unsigned report: present, but not signed."""
    return CertificationSeal(
        format_version=SEAL_FORMAT,
        report_sha256=report_digest(report),
        signer_public_key="",
        signer_key_fingerprint="",
        signature="",
        sealed_at=datetime.now(UTC),
    )


def _seal_payload(report: CertificationReport) -> bytes:
    """The exact bytes a seal's signature is made over."""
    return b"\n".join((SEAL_FORMAT.encode(), report_digest(report).encode()))


def report_digest(report: CertificationReport) -> str:
    """SHA-256 over the report's canonical JSON — what a seal answers for."""
    return sha256_hex(report_to_json(report).encode())


def verify_certification(
    report: CertificationReport,
    seal: CertificationSeal,
    *,
    trusted_public_key: str | None = None,
) -> str:
    """Verify a seal against its report; return the verifying key fingerprint.

    Fails closed on every mismatch: wrong seal or report format, report bytes
    that no longer digest to the sealed digest (the report was edited after
    sealing), a stored status that disagrees with the report's own recorded
    results, malformed key or signature material, a bad signature, or — when
    ``trusted_public_key`` is supplied — a seal made by any other key. The
    last check is what turns authenticity into publisher origin: the seal
    records who signed; the caller decides who to trust.
    """
    if seal.format_version != SEAL_FORMAT:
        raise CertificationInvalid(f"unsupported seal format: {seal.format_version!r}")
    if report.format_version != CERTIFICATION_FORMAT:
        raise CertificationInvalid(f"unsupported report format: {report.format_version!r}")
    if _report_status(report) != (report.certified, report.refusals):
        raise CertificationInvalid(
            "report status does not follow from its recorded results; the report "
            "was edited after certification"
        )
    if report_digest(report) != seal.report_sha256:
        raise CertificationInvalid(
            "report digest does not match the sealed digest; the report was modified after sealing"
        )
    if not seal.signed:
        raise CertificationInvalid("seal carries no signature; nothing was verified")
    if trusted_public_key is not None and seal.signer_public_key != trusted_public_key:
        raise CertificationInvalid("seal was made by a key other than the trusted public key")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(seal.signer_public_key))
        signature_bytes = bytes.fromhex(seal.signature)
    except ValueError as exc:
        raise CertificationInvalid("seal key or signature is not valid hex") from exc
    try:
        public_key.verify(signature_bytes, _seal_payload(report))
    except _InvalidSignature as exc:
        raise CertificationInvalid("seal signature does not verify over the report digest") from exc
    return seal.signer_key_fingerprint


def verify_certified_package(report: CertificationReport, bundle: ExtensionBundle) -> None:
    """Refuse any package whose bytes are not the certified ones.

    The acceptance criterion "later package mutation invalidates the
    signature/certification association" lives here: the association is the
    digest, so one flipped byte in the manifest, the payload, or any
    packaged source makes the bundle a different package, and the old
    certification no longer describes it. The failure names its layer.
    """
    subject = report.subject
    if bundle.digest() == subject.package_sha256:
        return
    detail = "package bytes no longer match the certification"
    if sha256_hex(bundle.manifest_bytes) != subject.manifest_sha256:
        detail = "manifest bytes no longer match the certification"
    elif sha256_hex(bundle.payload) != subject.artifact_sha256:
        detail = "artifact bytes no longer match the certification"
    raise CertificationPackageMismatch(
        f"{detail}: bundle digests to {bundle.digest()}, "
        f"certification covers {subject.package_sha256}"
    )


def certification_as_trust_claim(
    report: CertificationReport,
    seal: CertificationSeal,
    *,
    presented_manifest: bytes,
    presented_payload: bytes,
    trusted_public_key: str | None = None,
) -> TrustClaim:
    """Consume a certification as install-time trust evidence — and only that.

    Verifies the seal, refuses a certification that did not pass, and
    refuses when the manifest/payload bytes in hand are not the certified
    ones. The returned :class:`~maistro.extensions.types.TrustClaim` feeds
    the governed install flow's trust evaluation; it is evidence about the
    publisher and the bytes, never an authorization decision — the install
    lifecycle still requires the explicit operator approval before any code
    loads.
    """
    verify_certification(report, seal, trusted_public_key=trusted_public_key)
    if not report.certified:
        raise CertificationInvalid(
            "certification did not pass; it cannot back trust evidence "
            f"(refusals: {'; '.join(report.refusals)})"
        )
    if sha256_hex(presented_manifest) != report.subject.manifest_sha256:
        raise CertificationPackageMismatch(
            "presented manifest bytes are not the certified manifest"
        )
    if sha256_hex(presented_payload) != report.subject.artifact_sha256:
        raise CertificationPackageMismatch(
            "presented artifact bytes are not the certified artifact"
        )
    return TrustClaim(
        publisher_id=report.subject.publisher,
        signature_present=True,
        signer_key_id=seal.signer_key_fingerprint,
        package_sha256=report.subject.artifact_sha256,
    )


# ---------------------------------------------------------------------------
# Serialization: CI-friendly JSON, stable and self-verifying
# ---------------------------------------------------------------------------


def report_to_json(report: CertificationReport) -> str:
    """Serialize a report to stable JSON (sorted keys, ISO timestamps)."""
    payload = {
        "format": report.format_version,
        "profile": report.profile,
        "required_checks": list(report.required_checks),
        "certified": report.certified,
        "refusals": list(report.refusals),
        "claims": list(report.certified_claims),
        "subject": {
            "extension_id": report.subject.extension_id,
            "version": report.subject.version,
            "publisher": report.subject.publisher,
            "api_version": report.subject.api_version,
            "manifest_sha256": report.subject.manifest_sha256,
            "artifact_sha256": report.subject.artifact_sha256,
            "artifact_size": report.subject.artifact_size,
            "package_sha256": report.subject.package_sha256,
        },
        "environment": {
            "sdk_name": report.environment.sdk_name,
            "sdk_version": report.environment.sdk_version,
            "certifier_version": report.environment.certifier_version,
            "host": report.environment.host,
            "backend": report.environment.backend,
            "python_version": report.environment.python_version,
            "platform": report.environment.platform,
            "executed_at": report.environment.executed_at.isoformat(),
        },
        "checks": [
            {
                "id": result.check_id,
                "title": result.title,
                "outcome": result.outcome.value,
                "executed": result.executed,
                "detail": result.detail,
                "claims": list(result.claims),
                "earned_claims": list(result.earned_claims),
            }
            for result in report.results
        ],
    }
    return json.dumps(payload, sort_keys=True)


def report_from_json(raw: str) -> CertificationReport:
    """Rebuild a report from its JSON, re-deriving its status.

    A report whose stored ``certified``/``refusals`` disagree with what its
    recorded results and required checks actually imply is refuseable here —
    the same derivation certification used, applied on load. (Authenticity
    of an unmodified report is the seal's job; this check is structural.)
    """
    payload: dict[str, Any] = json.loads(raw)
    if payload.get("format") != CERTIFICATION_FORMAT:
        raise CertificationInvalid(f"unsupported report format: {payload.get('format')!r}")
    results = tuple(
        CheckResult(
            check_id=entry["id"],
            title=entry["title"],
            outcome=CheckOutcome(entry["outcome"]),
            detail=entry["detail"],
            claims=tuple(entry["claims"]),
        )
        for entry in payload["checks"]
    )
    required = tuple(payload["required_checks"])
    certified, refusals = _evaluate(results, required)
    if certified != payload["certified"] or list(refusals) != list(payload["refusals"]):
        raise CertificationInvalid(
            "report status does not follow from its recorded results; the report "
            "was edited after certification"
        )
    return CertificationReport(
        format_version=payload["format"],
        profile=payload["profile"],
        required_checks=required,
        subject=_subject_from_json(payload["subject"]),
        environment=_environment_from_json(payload["environment"]),
        results=results,
        certified=certified,
        refusals=refusals,
    )


def _subject_from_json(payload: dict[str, Any]) -> CertificationSubject:
    """Rebuild the subject block of a report."""
    return CertificationSubject(
        extension_id=payload["extension_id"],
        version=payload["version"],
        publisher=payload["publisher"],
        api_version=payload["api_version"],
        manifest_sha256=payload["manifest_sha256"],
        artifact_sha256=payload["artifact_sha256"],
        artifact_size=payload["artifact_size"],
        package_sha256=payload["package_sha256"],
    )


def _environment_from_json(payload: dict[str, Any]) -> CertificationEnvironment:
    """Rebuild the environment block of a report."""
    executed_at = datetime.fromisoformat(payload["executed_at"])
    if executed_at.tzinfo is None:
        executed_at = executed_at.replace(tzinfo=UTC)
    return CertificationEnvironment(
        sdk_name=payload["sdk_name"],
        sdk_version=payload["sdk_version"],
        certifier_version=payload["certifier_version"],
        host=payload["host"],
        backend=payload["backend"],
        python_version=payload["python_version"],
        platform=payload["platform"],
        executed_at=executed_at,
    )


def seal_to_json(seal: CertificationSeal) -> str:
    """Serialize a seal to stable JSON."""
    payload = {
        "format": seal.format_version,
        "report_sha256": seal.report_sha256,
        "signer_public_key": seal.signer_public_key,
        "signer_key_fingerprint": seal.signer_key_fingerprint,
        "signature": seal.signature,
        "sealed_at": seal.sealed_at.isoformat(),
    }
    return json.dumps(payload, sort_keys=True)


def seal_from_json(raw: str) -> CertificationSeal:
    """Rebuild a seal from its JSON."""
    payload: dict[str, Any] = json.loads(raw)
    if payload.get("format") != SEAL_FORMAT:
        raise CertificationInvalid(f"unsupported seal format: {payload.get('format')!r}")
    sealed_at = datetime.fromisoformat(payload["sealed_at"])
    if sealed_at.tzinfo is None:
        sealed_at = sealed_at.replace(tzinfo=UTC)
    return CertificationSeal(
        format_version=payload["format"],
        report_sha256=payload["report_sha256"],
        signer_public_key=payload["signer_public_key"],
        signer_key_fingerprint=payload["signer_key_fingerprint"],
        signature=payload["signature"],
        sealed_at=sealed_at,
    )


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------


def _summary_subject_lines(report: CertificationReport) -> list[str]:
    """The identity, digest and environment lines of a report summary."""
    subject = report.subject
    return [
        (
            f"  extension: {subject.extension_id or '(unidentified)'}@"
            f"{subject.version or '?'} by {subject.publisher or '(unknown publisher)'}"
            f" (api {subject.api_version or '?'})"
        ),
        f"  package:   sha256:{subject.package_sha256}",
        f"  manifest:  sha256:{subject.manifest_sha256}",
        f"  artifact:  sha256:{subject.artifact_sha256} ({subject.artifact_size} bytes)",
        (
            f"  environment: {report.environment.sdk_name} {report.environment.sdk_version} "
            f"(certifier {report.environment.certifier_version}), "
            f"host {report.environment.host}, backend {report.environment.backend}, "
            f"python {report.environment.python_version}, {report.environment.platform}"
        ),
        f"  executed at: {report.environment.executed_at.isoformat()}",
    ]


def _summary_claims_lines(report: CertificationReport) -> list[str]:
    """The claims block: only earned claims, or the none-earned admission."""
    if not report.certified_claims:
        return ["  claims: none earned"]
    lines = ["  claims:"]
    lines.extend(f"    - {claim}" for claim in report.certified_claims)
    return lines


def _summary_refusal_lines(report: CertificationReport) -> list[str]:
    """The refusals block, naming every cause in full."""
    if not report.refusals:
        return []
    lines = ["  refusals:"]
    lines.extend(f"    - {refusal}" for refusal in report.refusals)
    return lines


def _summary_seal_line(seal: CertificationSeal | None) -> str:
    """One line saying exactly what the seal can prove."""
    if seal is None:
        return "  seal: none"
    if not seal.signed:
        return "  seal: unsigned"
    return (
        f"  seal: signed by {seal.signer_key_fingerprint[:12]}… "
        f"over report sha256:{seal.report_sha256}"
    )


def render_summary(report: CertificationReport, seal: CertificationSeal | None = None) -> str:
    """A human-readable one-screen summary of a certification report.

    Plain text, no control sequences: the same string is at home in a CI job
    log, a terminal, and a release ticket. Every check's outcome is shown as
    recorded, claims are listed only as earned, and refusals are named in
    full.
    """
    verdict = "CERTIFIED" if report.certified else "NOT CERTIFIED"
    lines = [
        f"Extension certification: {verdict} (profile: {report.profile})",
        *_summary_subject_lines(report),
        "  checks:",
    ]
    for result in report.results:
        marker = "x" if result.outcome is CheckOutcome.PASSED else " "
        lines.append(f"    [{marker}] {result.check_id}: {result.outcome.value} — {result.detail}")
    lines.extend(_summary_claims_lines(report))
    lines.extend(_summary_refusal_lines(report))
    lines.append(_summary_seal_line(seal))
    return "\n".join(lines)
