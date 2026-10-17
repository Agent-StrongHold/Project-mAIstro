#!/usr/bin/env python3
"""Run a Pi recovery tool from either a checkout or an operator-owned install."""

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

COMMANDS = {
    "resume": "maistro_pi_resume",
    "start": "maistro_pi_start",
    "pane": "maistro_pi_pane",
    "foremen": "foremen",
    "observe": "check_foremen",
    "configure": "configure",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    # Only this reviewed package directory is added. No environment values or
    # arbitrary module names are evaluated as code or interpolated into a shell.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    tool = importlib.import_module("pi_recovery." + COMMANDS[args.command])
    try:
        return tool.main(args.arguments)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error), "progress_verified": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
