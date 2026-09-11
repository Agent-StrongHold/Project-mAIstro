#!/usr/bin/env python3
"""Run the fail-closed M1 cross-product parity closeout suite.

Development parity tests may report named dependency blockers. This invocation is
for a closure candidate only: every required scenario must execute a real
producer and observer/control boundary, and the pytest process must fail for an
unavailable or abstaining seam.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    env = os.environ.copy()
    env["MAISTRO_PARITY_MODE"] = "m1-closeout"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/cross_product_parity",
        "-q",
        "-s",
    ]
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
