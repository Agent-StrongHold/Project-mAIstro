"""Small safe process launcher used to apply limits without ``preexec_fn``."""

from __future__ import annotations

import os
import resource
import sys


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
    os.execvp(args[separator + 1], args[separator + 1 :])
    return 127


if __name__ == "__main__":  # pragma: no cover - process exits through execvp
    raise SystemExit(main())
