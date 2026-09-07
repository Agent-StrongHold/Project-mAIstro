"""The candidate-execution environment for evolve's test-executing gates (#78).

``maistro-evolve`` cannot add a package dependency on ``maistro-core`` — the
dependency direction is otherwise reversed, the same convention
``benchmarks/sandbox_exec.py`` documents for its sandbox delegation. But
``tdd_gate``, ``coverage_gate`` and the mutation probe execute
candidate-importing pytest (the candidate's ``conftest``, fixtures and
declared plugins run in that process tree), so they need the same credential
boundary the RSI runtime uses: a fixed minimal base, never ambient
inheritance.

The canonical base lives in ``maistro.sandbox.credential_boundary``. When core
is importable — the integrated RSI/evolve runtime always provides it — this
module delegates to the canonical function directly. The inline fallback below
mirrors it exactly, so a standalone evolve install keeps the *same minimal
posture* rather than falling back to ambient inheritance: a fallback that
weakened isolation would invert the point of the boundary. The two definitions
are pinned together by test (``test_candidate_env_equivalence``), which runs
wherever core is present, so they cannot drift silently.
"""

from __future__ import annotations

import os

_FALLBACK_BASE: dict[str, str] = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TERM": "dumb",
    "PYTHONDONTWRITEBYTECODE": "1",
}

#: Mirrors the canonical module's Windows forwarding list — same doctrine as
#: the builders sandbox: by NAME from an allowlist, none carry credentials.
_WINDOWS_FORWARD_NAMES: tuple[str, ...] = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
)


def candidate_env() -> dict[str, str]:
    """The canonical candidate environment when core is importable, else the
    identical inline base. Never reads the ambient environment on POSIX."""
    try:
        from maistro.sandbox.credential_boundary import candidate_env as _canonical
    except ImportError:
        pass
    else:
        return _canonical()
    env = dict(_FALLBACK_BASE)
    if os.name == "nt":
        env.update(
            {name: value for name in _WINDOWS_FORWARD_NAMES if (value := os.environ.get(name))}
        )
    return env
