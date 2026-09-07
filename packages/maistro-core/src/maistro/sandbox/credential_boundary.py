"""The credential boundary between host environments and candidate execution.

Issue #78 (ADR-093 posture): unattended/candidate execution environments
receive **no ambient host credentials**. Before this module, every host-backed
candidate path inherited the harness process's whole environment — so an RSI
cycle inside an sbx microVM handed its own ``LITELLM_MASTER_KEY`` (the gateway
credential :mod:`maistro_rsi.gateway` reads from the environment) to the
candidate's ``bash -c`` via plain env inheritance, and the local loop's test
runner did the same for candidate ``conftest.py``. A candidate that ran ``env``
or read ``/proc/self/environ`` recovered credentials it was never authorized to
see — exactly the failure mode ADR-093's industry survey calls out: the
adversary "mostly doesn't need to escape", it exfiltrates what is reachable
*inside* the boundary.

The boundary is a value, not a filter. :func:`candidate_env` builds a
candidate's environment from a fixed minimal base plus the caller's *explicit*
grants and nothing else — it never consults :data:`os.environ` on POSIX, so
ambient inheritance is structurally impossible rather than filtered away
(allowlist filtering of an inherited dict always risks a new secret shape
slipping through; not reading the ambient dict at all cannot).

Permitted secrets cross only as explicit grants, and the sanctioned source of a
secret grant is a :class:`~maistro.credentials.types.CredentialRecord` acquired
through :meth:`~maistro.credentials.router.CredentialRouter.acquire` under a
Binding's Workspace/Project scope (#58/#1041 moved selection there).
:func:`grant_from_credential` is that crossing: it accepts only the router's
record type, so provenance — scoped, Binding-authorized, outcome-rotated — is
structural, not a naming convention. Grants die with the sandbox process, which
is the short-lived property available at this tier.

What this module does not claim: filesystem isolation. A candidate whose
sandbox mounts the operator's real home still sees whatever files live there —
that is the substrate's job (``ContainerBuilderSandbox``'s host-side seed
denylist, bubblewrap's mount namespace), not the environment's.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from types import MappingProxyType

from maistro.credentials.types import CredentialRecord

#: The environment every candidate/unattended exec starts from. Fixed values
#: only — PATH is a literal, never the host's, so an ambient PATH pointing at
#: a credential-helper-stuffed bin directory cannot ride along. HOME and USER
#: are deliberately absent: an inherited HOME points the candidate at the
#: operator's config files (``.netrc``, ``.aws``, ``.gitconfig``) for free.
#: Tools fall back to the passwd entry, which inside a disposable sandbox
#: user is the honest answer.
CANDIDATE_BASE_ENV: Mapping[str, str] = MappingProxyType(
    {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        # Bytecode caches written by candidate code outlive the sandbox on
        # host-backed paths; this was tdd_gate's own reason and moves here.
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)

#: Names a grant may never shadow. A grant overriding ``PATH`` (or any other
#: base name) would let caller-side data widen the base posture — the same
#: widening #78 forbids for candidates, applied to the grant channel itself.
_RESERVED_NAMES: frozenset[str] = frozenset(CANDIDATE_BASE_ENV)

#: Windows children cannot start without the system basics (python.exe fails
#: in ``_Py_HashRandomization_init`` without SYSTEMROOT; executable lookup
#: needs the real PATH). Same doctrine as the builders sandbox: forwarded BY
#: NAME from an allowlist — still no ``os.environ`` spread, and none of these
#: carry credentials, so the no-ambient-secrets property holds unchanged.
_WINDOWS_FORWARD_NAMES: tuple[str, ...] = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
)


def candidate_env(explicit: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment for one candidate/unattended exec.

    Built from :data:`CANDIDATE_BASE_ENV` plus ``explicit`` grants. Ambient
    inheritance is impossible by construction: on POSIX the ambient
    environment is never read; on Windows only the five non-secret names in
    :data:`_WINDOWS_FORWARD_NAMES` are forwarded, by name.

    Raises :class:`ValueError` if a grant tries to shadow a base name — a
    grant widens what the candidate may *use*, never what the boundary
    guarantees.
    """
    env = dict(CANDIDATE_BASE_ENV)
    if os.name == "nt":
        env.update(
            {name: value for name in _WINDOWS_FORWARD_NAMES if (value := os.environ.get(name))}
        )
    for name, value in (explicit or {}).items():
        if name in _RESERVED_NAMES:
            raise ValueError(
                f"credential grant {name!r} shadows the sandbox base environment; "
                "grants may add variables, never override the boundary's own"
            )
        env[name] = value
    return env


def grant_from_credential(record: CredentialRecord, env_name: str) -> dict[str, str]:
    """The one sanctioned way a secret enters a candidate environment.

    ``record`` must be a :class:`CredentialRecord` — the type
    :meth:`~maistro.credentials.router.CredentialRouter.acquire` returns under
    a Binding's Workspace/Project scope and ``credential_refs`` authorization.
    Type-gating the parameter makes provenance structural: a bare string key
    has no scope, no cooldown, and no Binding that authorized it, so it does
    not get to pretend it came from the pool.
    """
    if not isinstance(record, CredentialRecord):
        raise TypeError(
            "credential grants must originate from a CredentialRouter acquisition "
            f"(CredentialRecord), not ambient material: got {type(record).__name__}"
        )
    if env_name in _RESERVED_NAMES:
        raise ValueError(f"credential grant name {env_name!r} shadows the sandbox base environment")
    return {env_name: record.api_key}


def redact_env(env: Mapping[str, str]) -> dict[str, str]:
    """A logging-safe view of a candidate environment: names stay, values go.

    Permitted secrets must be "redacted from logs/events" (#78 AC-3); masking
    the value entirely — rather than truncating or hashing it — is the only
    form that cannot be brute-forced back from a short prefix or a salted
    digest of a low-entropy key.
    """
    return dict.fromkeys(env, "***")


__all__ = [
    "CANDIDATE_BASE_ENV",
    "candidate_env",
    "grant_from_credential",
    "redact_env",
]
