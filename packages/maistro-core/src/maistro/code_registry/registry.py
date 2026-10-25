"""In-memory code registry: resolve/compatible/signature core (SPEC-257 / ADR-069)."""

from __future__ import annotations

import re

from maistro.code_registry.types import CodeEntry, CodeRefUnresolved, InvalidSignature
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
    def __init__(self) -> None:
        self._entries: dict[str, CodeEntry] = {}

    def register(self, entry: CodeEntry, *, verifier: SignatureVerifier) -> None:
        if not entry.version:
            raise CodeRefUnresolved(f"unversioned entry: {entry.name!r}")
        payload = f"{entry.name}@{entry.version}:{entry.code_sha256}".encode()
        if not verifier.verify(payload, entry.signature):
            raise InvalidSignature(f"invalid signature for {entry.name}@{entry.version}")
        self._entries[f"{entry.name}@{entry.version}"] = entry

    def resolve(self, ref: str) -> CodeEntry:
        _parse_ref(ref)
        entry = self._entries.get(ref)
        if entry is None:
            raise CodeRefUnresolved(f"no registered entry for ref: {ref!r}")
        return entry

    def compatible(self, base_ref: str, overlay_ref: str) -> bool:
        _, base_version = _parse_ref(base_ref)
        _, overlay_version = _parse_ref(overlay_ref)
        base_major, _, _ = _parse_semver(base_version)
        overlay_major, _, _ = _parse_semver(overlay_version)
        return base_major == overlay_major
