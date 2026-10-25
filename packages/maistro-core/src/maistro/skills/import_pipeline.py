"""Medley import sanitization pipeline (SPEC-062126-d421, implements ADR-083).

One fail-closed gate for every skill import — registry, URL, upload, or paste:
scan, salvage-or-block, re-scan, register sandboxed at T3, and bind a
content-hash policy attachment so the payload is re-scanned on every use
(rug-pull defense, ledger entries 6 and 13).

This module composes existing primitives (``parser.security_scan``,
``fixer.fix_content``, ``marketplace`` SSRF blocking, ``forge``, ``canary``)
— it does not reimplement scanning.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from maistro.skills.fixer import fix_content
from maistro.skills.marketplace import _block_ssrf
from maistro.skills.parser import MAX_SKILL_BODY_LENGTH, parse_skill_file, security_scan
from maistro.types.skill import SkillDefinition

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from maistro.security.sentinel.authz_types import Principal
    from maistro.skills.canary import CanaryManager
    from maistro.skills.marketplace import HTTPClient
    from maistro.skills.registry import InMemorySkillRegistry

logger = logging.getLogger("maistro.skills.import_pipeline")

IMPORT_TRUST_TIER = "t3"
"""Every import registers sandboxed at T3, regardless of source (ADR-083).

Only the SPEC-005 signing path may raise the tier — never this pipeline.
"""


class ImportSource(StrEnum):
    """Where an imported skill came from. Provenance never skips scanning."""

    REGISTRY = "registry"  # Medley/ClawHub
    URL = "url"
    UPLOAD = "upload"
    PASTE = "paste"


@dataclass(frozen=True)
class SkillImportRequest:
    """A request to bring a skill into the engine."""

    source: ImportSource
    importer: Principal
    raw: str | None = None  # paste/upload body
    url: str | None = None  # URL/registry import


@dataclass(frozen=True)
class SkillImportReport:
    """Structured, admin-readable outcome of an import attempt."""

    blocked: bool
    scan_issues: tuple[str, ...]  # security_scan findings on the original content
    fixes_applied: tuple[str, ...]  # what salvage changed
    unfixable_issues: tuple[str, ...]  # why it was refused (empty if registered)
    content_hash: str
    source: ImportSource
    source_ref: str | None  # URL/registry id for abuse escalation


@dataclass(frozen=True)
class SkillImportVerdict:
    """The gate's decision. Nothing installs on a non-``registered`` outcome."""

    outcome: Literal["registered", "blocked"]
    skill: SkillDefinition | None  # set iff registered
    trust_tier: Literal["t3"] | None  # imports always start sandboxed
    report: SkillImportReport


@dataclass(frozen=True)
class PolicyAttachment:
    """Sentinel policy attachment binding a skill to its scanned content hash.

    Recorded at registration; the per-use boundary re-checks the hash and
    re-scans the payload, so a post-import mutation is denied at execution.
    """

    skill_name: str
    content_hash: str
    policy: str = "rescan_on_use"


@runtime_checkable
class PolicyAttachmentStore(Protocol):
    """Storage for per-skill Sentinel policy attachments."""

    def attach(self, attachment: PolicyAttachment) -> None: ...

    def get(self, skill_name: str) -> PolicyAttachment | None: ...


class InMemoryPolicyAttachmentStore:
    """Thread-safe in-memory PolicyAttachmentStore."""

    def __init__(self) -> None:
        self._attachments: dict[str, PolicyAttachment] = {}
        self._lock = threading.RLock()

    def attach(self, attachment: PolicyAttachment) -> None:
        with self._lock:
            self._attachments[attachment.skill_name] = attachment

    def get(self, skill_name: str) -> PolicyAttachment | None:
        with self._lock:
            return self._attachments.get(skill_name)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _blocked(
    request: SkillImportRequest,
    *,
    scan_issues: tuple[str, ...],
    fixes_applied: tuple[str, ...],
    unfixable_issues: tuple[str, ...],
    content_hash: str,
    emit: Callable[[str, Mapping[str, Any]], None] | None,
) -> SkillImportVerdict:
    """Build a blocked verdict and emit the ``security.violation`` event."""
    report = SkillImportReport(
        blocked=True,
        scan_issues=scan_issues,
        fixes_applied=fixes_applied,
        unfixable_issues=unfixable_issues,
        content_hash=content_hash,
        source=request.source,
        source_ref=request.url,
    )
    if emit is not None:
        emit(
            "security.violation",
            {
                "boundary": "skill_import",
                "source": request.source.value,
                "source_ref": request.url,
                "importer": request.importer.id,
                "unfixable_issues": list(unfixable_issues),
                "scan_issues": list(scan_issues),
                "content_hash": content_hash,
            },
        )
    logger.warning(
        "Skill import BLOCKED (source=%s, ref=%s): %s",
        request.source.value,
        request.url,
        "; ".join(unfixable_issues),
    )
    return SkillImportVerdict(outcome="blocked", skill=None, trust_tier=None, report=report)


async def _fetch_content(
    request: SkillImportRequest,
    http_client: HTTPClient | None,
) -> tuple[str | None, str | None]:
    """Step 1: fetch/normalize per source. Returns (content, error)."""
    if request.source in (ImportSource.URL, ImportSource.REGISTRY) and request.url:
        try:
            _block_ssrf(request.url)  # SSRF denylist BEFORE any fetch/parse
        except ValueError as e:
            return None, str(e)
        if http_client is None:
            return None, "No HTTP client available for URL import"
        try:
            resp = await http_client.get(request.url)
        except Exception as e:
            return None, f"Failed to fetch skill from {request.url}: {e}"
        if resp.status_code != 200:
            return None, f"Skill fetch returned {resp.status_code} from {request.url}"
        return resp.text, None

    if request.source in (ImportSource.UPLOAD, ImportSource.PASTE) and request.raw is not None:
        return request.raw, None
    return None, "Import request has no content (missing raw body or url)"


async def _fetch_and_bound(
    request: SkillImportRequest,
    http_client: HTTPClient | None,
    emit: Callable[[str, Mapping[str, Any]], None] | None,
) -> tuple[str | None, SkillImportVerdict | None]:
    """Step 1: fetch per source and enforce the body-length bound (fail-closed)."""
    content, fetch_error = await _fetch_content(request, http_client)
    if content is None or fetch_error is not None:
        return None, _blocked(
            request,
            scan_issues=(),
            fixes_applied=(),
            unfixable_issues=(fetch_error or "no content",),
            content_hash="",
            emit=emit,
        )
    if len(content) > MAX_SKILL_BODY_LENGTH:
        return None, _blocked(
            request,
            scan_issues=(),
            fixes_applied=(),
            unfixable_issues=(
                f"Content exceeds MAX_SKILL_BODY_LENGTH ({len(content)} > {MAX_SKILL_BODY_LENGTH})",
            ),
            content_hash=_hash(content),
            emit=emit,
        )
    return content, None


async def _improve_and_rescan(
    request: SkillImportRequest,
    fixed: str,
    improve: Callable[[str], Awaitable[str]] | None,
    *,
    scan_issues: tuple[str, ...],
    fixes: tuple[str, ...],
    emit: Callable[[str, Mapping[str, Any]], None] | None,
) -> tuple[str, SkillImportVerdict | None]:
    """Step 5: optional forge improve; its output is never trusted and is re-scanned."""
    if improve is None:
        return fixed, None
    improved = await improve(fixed)
    safe_improved, improved_findings = security_scan(improved)
    if not safe_improved:
        return fixed, _blocked(
            request,
            scan_issues=scan_issues,
            fixes_applied=fixes,
            unfixable_issues=tuple(
                f"forge_output:{f}" for f in improved_findings if f.startswith("CRITICAL:")
            ),
            content_hash=_hash(improved),
            emit=emit,
        )
    return improved, None


async def _scan_and_salvage(
    request: SkillImportRequest,
    content: str,
    warden_scan: Callable[[str, str], Awaitable[Any]] | None,
    emit: Callable[[str, Mapping[str, Any]], None] | None,
) -> tuple[str, tuple[str, ...], tuple[str, ...], SkillImportVerdict | None]:
    """Steps 2-4: scan (parser + Warden), salvage-or-block, re-scan salvage output."""
    _safe, findings = security_scan(content)
    scan_issues = tuple(findings)
    if warden_scan is not None:
        verdict = await warden_scan(content, "skill_import")
        flags = getattr(verdict, "flags", ())
        scan_issues = scan_issues + tuple(f"warden:{f}" for f in flags)

    fixed, fixes_list, unfixable = fix_content(content)
    fixes = tuple(fixes_list)
    if unfixable:
        return (
            fixed,
            scan_issues,
            fixes,
            _blocked(
                request,
                scan_issues=scan_issues,
                fixes_applied=fixes,
                unfixable_issues=tuple(unfixable),
                content_hash=_hash(content),
                emit=emit,
            ),
        )

    safe_after, residual = security_scan(fixed)
    if not safe_after:
        return (
            fixed,
            scan_issues,
            fixes,
            _blocked(
                request,
                scan_issues=scan_issues,
                fixes_applied=fixes,
                unfixable_issues=tuple(f for f in residual if f.startswith("CRITICAL:")),
                content_hash=_hash(fixed),
                emit=emit,
            ),
        )
    return fixed, scan_issues, fixes, None


async def import_skill(
    request: SkillImportRequest,
    *,
    registry: InMemorySkillRegistry,
    policy_store: PolicyAttachmentStore,
    http_client: HTTPClient | None = None,
    warden_scan: Callable[[str, str], Awaitable[Any]] | None = None,
    improve: Callable[[str], Awaitable[str]] | None = None,
    canary: CanaryManager | None = None,
    emit: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> SkillImportVerdict:
    """Run the full import sanitization pipeline (SPEC-062126-d421).

    Fail-closed at every stage: fetch/bound -> scan -> salvage-or-block ->
    re-scan -> optional improve (always re-scanned) -> parse -> register at
    T3 with canary -> bind content-hash for re-scan-on-use.

    Args:
        warden_scan: optional ``async (content, boundary) -> WardenVerdict``
            (e.g. ``Warden.scan``), run at boundary ``"skill_import"``.
        improve: optional LLM improvement pass; its output is never trusted
            and is re-scanned like any other content.
        emit: event emitter; blocked verdicts emit ``security.violation``.
    """
    # 1. Fetch + bound.
    content, blocked = await _fetch_and_bound(request, http_client, emit)
    if blocked is not None:
        return blocked
    assert content is not None

    # 2-4. Scan, salvage-or-block, re-scan the salvaged content.
    fixed, scan_issues, fixes, salvage_blocked = await _scan_and_salvage(
        request, content, warden_scan, emit
    )
    if salvage_blocked is not None:
        return salvage_blocked

    # 5. Optional improve (never trusted) + parse.
    fixed, improve_blocked = await _improve_and_rescan(
        request, fixed, improve, scan_issues=scan_issues, fixes=fixes, emit=emit
    )
    if improve_blocked is not None:
        return improve_blocked

    source_ref = request.url or request.source.value
    parsed = parse_skill_file(fixed, source=source_ref)
    if parsed is None:
        return _blocked(
            request,
            scan_issues=scan_issues,
            fixes_applied=fixes,
            unfixable_issues=("Content failed to parse as a SkillDefinition",),
            content_hash=_hash(fixed),
            emit=emit,
        )

    # 6. Register sandboxed at T3 regardless of source, roll out via canary.
    skill = SkillDefinition(
        name=parsed.name,
        description=parsed.description,
        groups=parsed.groups,
        parameters=parsed.parameters,
        endpoint=parsed.endpoint,
        auth_key_env=parsed.auth_key_env,
        system_prompt=parsed.system_prompt,
        source=source_ref,
        trust_tier=IMPORT_TRUST_TIER,
    )
    registry.register(skill)
    if canary is not None:
        canary.start_canary(skill.name, old_version=0, new_version=1)

    # 7. Bind content_hash as a Sentinel policy attachment (re-scan-on-use).
    content_hash = _hash(fixed)
    policy_store.attach(PolicyAttachment(skill_name=skill.name, content_hash=content_hash))

    report = SkillImportReport(
        blocked=False,
        scan_issues=scan_issues,
        fixes_applied=fixes,
        unfixable_issues=(),
        content_hash=content_hash,
        source=request.source,
        source_ref=request.url,
    )
    logger.info(
        "Skill import registered: %s (source=%s, tier=%s, fixes=%d)",
        skill.name,
        request.source.value,
        IMPORT_TRUST_TIER,
        len(fixes),
    )
    return SkillImportVerdict(outcome="registered", skill=skill, trust_tier="t3", report=report)


def verify_skill_payload(
    skill_name: str,
    payload: str,
    *,
    policy_store: PolicyAttachmentStore,
) -> tuple[bool, tuple[str, ...]]:
    """Per-use verification: content-hash check + fresh ``security_scan``.

    Returns ``(allowed, reasons)``. Denies on missing binding, hash mismatch
    (rug-pull defense, ledger entry 6), or a dirty re-scan.
    """
    reasons: list[str] = []
    attachment = policy_store.get(skill_name)
    if attachment is None:
        reasons.append(f"no rescan_on_use policy attachment for skill '{skill_name}'")
    elif _hash(payload) != attachment.content_hash:
        reasons.append("content_hash mismatch: payload mutated since import (rug-pull)")

    safe, findings = security_scan(payload)
    if not safe:
        reasons.extend(f for f in findings if f.startswith("CRITICAL:"))

    if reasons:
        logger.warning("Skill use DENIED for '%s': %s", skill_name, "; ".join(reasons))
        return False, tuple(reasons)
    return True, ()
