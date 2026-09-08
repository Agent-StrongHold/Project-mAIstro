"""The candidate-execution environment for evolve's test-executing gates (#78).

``maistro-evolve`` cannot add a package dependency on ``maistro-core`` — the
dependency direction is otherwise reversed, the same convention
``benchmarks/sandbox_exec.py`` documents for its sandbox delegation. But
``tdd_gate``, ``coverage_gate`` and the mutation probe execute
candidate-importing pytest (the candidate's ``conftest``, fixtures and
declared plugins run in that process tree), so they need the same credential
boundary the RSI runtime uses: a fixed minimal base, never ambient
inheritance.

The canonical specification lives in
``maistro.sandbox.credential_boundary`` (maistro-core) — but this seam MUST
NOT import it, not even lazily inside a try/except. Two independent reasons,
both load-bearing:

1. ``maistro/sandbox/__init__.py`` re-exports the whole sandbox subsystem, so
   any import of the leaf module drags that package initializer — and through
   it the wider core — onto the promotion path. ``scripts/check-promotion-surface.py``
   walks the import graph from the promotion roots (this package included) and
   reads the AST, as it must: a function-level import is still an import edge.
   The promotion path may reach only protected or tolerated surfaces, and the
   general-purpose core cascade is neither.
2. A standalone evolve install has no maistro-core to delegate to anyway.

So the boundary is re-implemented here, exactly, and the two definitions are
pinned together by test (``test_candidate_env_equivalence``, which runs
wherever core is present and imports both modules directly — test code is not
on the promotion path), so they cannot drift silently. A drift would make the
two runtimes give candidates different environments, and the weaker one would
win; the test is what makes "exactly" a property the tree enforces rather
than a claim this docstring makes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from types import MappingProxyType

#: Mirrors ``maistro.sandbox.credential_boundary.CANDIDATE_BASE_ENV`` exactly.
#: Fixed values only — PATH is a literal, never the host's, so an ambient PATH
#: pointing at a credential-helper-stuffed bin directory cannot ride along.
#: HOME and USER are deliberately absent: an inherited HOME points the
#: candidate at the operator's config files (``.netrc``, ``.aws``,
#: ``.gitconfig``) for free.
CANDIDATE_BASE_ENV: Mapping[str, str] = MappingProxyType(
    {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        # Bytecode caches written by candidate code outlive the sandbox on
        # host-backed paths; tdd_gate's original reason, kept in the base.
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)

#: Names a grant may never shadow — same rule as the canonical module: a
#: grant overriding a base name would let caller-side data widen the base
#: posture (#78 applied to the grant channel itself).
_RESERVED_NAMES: frozenset[str] = frozenset(CANDIDATE_BASE_ENV)

#: Mirrors the canonical module's Windows forwarding list — same doctrine as
#: the builders sandbox: forwarded BY NAME from an allowlist, none of these
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
    guarantees. Identical semantics to the canonical
    ``maistro.sandbox.credential_boundary.candidate_env``, pinned by
    ``test_candidate_env_equivalence``.
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
