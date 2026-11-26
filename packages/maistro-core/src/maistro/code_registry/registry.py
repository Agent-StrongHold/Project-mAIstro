"""In-memory code registry: resolve/compatible/signature core (SPEC-257 / ADR-069)."""

from __future__ import annotations

import re

from maistro.code_registry.types import (
    CodeEntry,
    CodeEntryConflict,
    CodeRefUnresolved,
    InvalidSignature,
)
from maistro.code_registry.verify import SignatureVerifier

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_ref(ref: str) -> tuple[str, str]:
    if "@" not in ref:
        raise CodeRefUnresolved(f"unversioned ref: {ref!r}")
    name, _, version = ref.partition("@")
    if not version:
        raise CodeRefUnresolved(f"unversioned ref: {ref!r}")
    return name, version


def _parse_semver(version: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.match(version)
    if match is None:
        raise CodeRefUnresolved(f"not a valid semver version: {version!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


class CodeRegistry:
    def __init__(self, *, verifier: SignatureVerifier | None = None) -> None:
        self._entries: dict[str, CodeEntry] = {}
        self._verifiers: dict[str, SignatureVerifier] = {}
        self._default_verifier = verifier

    @staticmethod
    def signing_payload(entry: CodeEntry) -> bytes:
        """The exact bytes a registry signature must vouch for.

        This is every field the governed execution path trusts: the identity
        (``name@version``), the *kind* — which selects the Sentinel permission
        action (``code.invoke.<kind>``) and reversibility class at invoke time
        — and the content-addressed body. Signing the kind closes the
        relabeling hole where an entry signed under a restricted kind could be
        re-registered as a kind the principal is authorized to invoke while
        retaining the original valid signature.
        """
        return (f"{entry.name}@{entry.version}:{entry.kind.value}:{entry.code_sha256}").encode()

    @classmethod
    def _verify(cls, entry: CodeEntry, verifier: SignatureVerifier) -> None:
        if not verifier.verify(cls.signing_payload(entry), entry.signature):
            raise InvalidSignature(f"invalid signature for {entry.name}@{entry.version}")

    def register(self, entry: CodeEntry, *, verifier: SignatureVerifier | None = None) -> None:
        if not entry.version:
            raise CodeRefUnresolved(f"unversioned entry: {entry.name!r}")
        active_verifier = verifier or self._default_verifier
        if active_verifier is None:
            raise InvalidSignature(f"no verifier configured for {entry.name}@{entry.version}")
        self._verify(entry, active_verifier)
        ref = f"{entry.name}@{entry.version}"
        existing = self._entries.get(ref)
        if existing is not None and existing != entry:
            # A rediscovery must not replace the code or its approval history.
            raise CodeEntryConflict(f"code ref already registered: {ref}")
        self._entries[ref] = entry
        self._verifiers[ref] = active_verifier

    load = register

    def resolve(self, ref: str) -> CodeEntry:
        _parse_ref(ref)
        entry = self._entries.get(ref)
        if entry is None:
            raise CodeRefUnresolved(f"no registered entry for ref: {ref!r}")
        verifier = self._verifiers.get(ref) or self._default_verifier
        if verifier is None:
            raise InvalidSignature(f"no verifier configured for {ref}")
        # Verification is repeated at the execution admission point. This
        # catches tampering of an entry between registration and resolution.
        self._verify(entry, verifier)
        return entry

    def compatible(self, base_ref: str, overlay_ref: str) -> bool:
        _, base_version = _parse_ref(base_ref)
        _, overlay_version = _parse_ref(overlay_ref)
        base_major, _, _ = _parse_semver(base_version)
        overlay_major, _, _ = _parse_semver(overlay_version)
        return base_major == overlay_major
