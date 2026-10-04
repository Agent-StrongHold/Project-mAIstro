"""Deterministic digests for evaluation workspaces.

Reproducibility (#107) rests on a question the sandbox substrate never had to
answer: *when are two environments the same environment?* Two eval branches can
only be compared against each other if they started identically, and "we think
they were the same image" is not a claim a comparison can stand on.

So every workspace environment reduces to one digest, computed the same way in
every process: canonical JSON (sorted keys, no whitespace variance, ASCII) over
the fields that define the environment, hashed with SHA-256. Two specs with
equal digests are interchangeable for matched comparisons; two specs that
differ anywhere -- fixture content, egress grant, resource limits, isolation
floor -- produce different digests, and a fork or restore across that
difference is refused rather than silently accepted.

The digest is computed from a *projection*, not from `dataclasses.asdict`:
`SandboxConfig` carries a fence slot and other fields whose repr is not
stable across processes, and a digest that depends on dict insertion order or
memory addresses is not a digest.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from maistro.sandbox.network import EgressGrant, EgressMode
from maistro.sandbox.protocol import SandboxConfig

#: Schema version for the digest projection. Bump when a field is added to the
#: projection in a way that changes meaning; old digests then fail closed
#: (mismatch) instead of silently comparing equal to new ones.
DIGEST_SCHEMA_VERSION = 1

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def canonical_json(value: Any) -> str:
    """Serialize deterministically: sorted keys, tight separators, ASCII.

    The same value produces the same string in every process, which is the
    only property a content digest can be built on.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_hex(payload: str | bytes) -> str:
    """Hex SHA-256 of a string (UTF-8) or bytes."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def content_digest(content: bytes) -> str:
    """Digest of captured workspace state (snapshot content or fixture bytes).

    Empty content hashes to the SHA-256 of the empty byte string -- an empty
    state is a state, not an absence.
    """
    return sha256_hex(content)


def _project_egress(grant: EgressGrant) -> dict[str, Any]:
    return {
        "mode": grant.mode.value if isinstance(grant.mode, EgressMode) else str(grant.mode),
        "allow": sorted(grant.allow),
        "reason": grant.reason,
    }


def _project_sandbox(config: SandboxConfig) -> dict[str, Any]:
    return {
        "memory_mb": config.memory_mb,
        "cpu_cores": config.cpu_cores,
        "timeout_s": config.timeout_s,
        "max_file_mb": config.max_file_mb,
        "max_processes": config.max_processes,
        "network": config.network,
        "writable_paths": sorted(config.writable_paths),
        "env": dict(sorted(config.env.items())),
        "min_isolation": config.min_isolation,
        "egress": _project_egress(config.egress),
    }


def environment_digest(
    *,
    image: str,
    sandbox: SandboxConfig,
    fixtures_digest: str,
) -> str:
    """The identity of an evaluation environment.

    `image` is the rootfs/filesystem identity the backend will start from (an
    image reference, an OCI digest, or a backend-specific snapshot id -- the
    substrate does not interpret it, it only folds it in). `fixtures_digest`
    is the manifest digest of the deterministic fixtures the environment is
    seeded with. Everything else comes from the frozen `SandboxConfig`.
    """
    projection = {
        "v": DIGEST_SCHEMA_VERSION,
        "image": image,
        "sandbox": _project_sandbox(sandbox),
        "fixtures": fixtures_digest,
    }
    return sha256_hex(canonical_json(projection))


__all__ = [
    "DIGEST_SCHEMA_VERSION",
    "canonical_json",
    "content_digest",
    "environment_digest",
    "sha256_hex",
]
