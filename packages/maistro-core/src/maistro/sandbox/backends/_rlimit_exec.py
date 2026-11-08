"""Small safe process launcher used to apply limits without ``preexec_fn``."""

from __future__ import annotations

import os
import resource
import signal
import sys

#: Signals CPython sets to ``SIG_IGN`` at interpreter start and that this helper
#: must hand back as ``SIG_DFL`` before it becomes the sandbox. The helper
#: ``execvp``s in place, so whatever disposition it leaves behind is inherited
#: by ``bwrap`` and by every workload process inside the sandbox.
#:
#: That matters for ``SIGXFSZ`` (#80): ignored, a write past ``RLIMIT_FSIZE``
#: returns ``EFBIG`` instead of killing the process, so a runaway write exits 1
#: with an error message rather than being stopped by the kernel. The ceiling is
#: still enforced, but the observable contract -- and the conformance test that
#: asserts it -- is a signal death. Python's own ``subprocess`` restores exactly
#: these in a forked child (``restore_signals``); the helper is the process that
#: execs the sandbox, so it does the same explicitly.
_RESTORED_SIGNALS = tuple(
    getattr(signal, name) for name in ("SIGPIPE", "SIGXFZ", "SIGXFSZ") if hasattr(signal, name)
)


def _restore_default_signals() -> None:
    for signum in _RESTORED_SIGNALS:
        try:
            signal.signal(signum, signal.SIG_DFL)
        except (OSError, ValueError):  # pragma: no cover - defensive; valid signals
            continue


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: python -m maistro.sandbox.backends._rlimit_exec RESOURCE SOFT HARD ... -- COMMAND",
            file=sys.stderr,
        )
        return 2
    args = sys.argv[1:]
    try:
        separator = args.index("--")
    except ValueError:
        print("missing command separator", file=sys.stderr)
        return 2
    if separator == len(args) - 1:
        print("missing command", file=sys.stderr)
        return 2
    if separator % 3:
        print("resource arguments must be triples", file=sys.stderr)
        return 2
    for offset in range(0, separator, 3):
        which = int(args[offset])
        soft = int(args[offset + 1])
        hard = int(args[offset + 2])
        resource.setrlimit(which, (soft, hard))
    _restore_default_signals()
    os.execvp(args[separator + 1], args[separator + 1 :])
    return 127


if __name__ == "__main__":  # pragma: no cover - process exits through execvp
    raise SystemExit(main())
