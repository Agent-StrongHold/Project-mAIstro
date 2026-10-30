#!/usr/bin/env python3
"""Create/attach managed tmux session pi; --boot keeps a Windows WSL client alive."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import maistro_pi_resume as recovery
from .recovery_paths import TMUX, bound_command

SESSION = "pi"


def tmux(*args, check=True):
    return subprocess.run([TMUX, *args], text=True, capture_output=True, check=check)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--boot", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument(
        "--ensure", action="store_true", help="create if absent, never attach or wait"
    )
    parser.add_argument("--state-dir", type=Path, default=recovery.DEFAULT_STATE)
    args = parser.parse_args(argv)
    state = args.state_dir.expanduser().resolve()
    config = recovery.load_config(state)
    channel = "maistro-pi-exit-" + config["sessionId"]
    pane = Path(__file__).resolve().with_name("cli.py")
    pane_command = bound_command(
        [sys.executable, str(pane), "pane", str(state), channel],
        PI_RECOVERY_STATE_DIR=str(state),
    )
    alive = recovery.owner_alive(config.get("owner"))
    exists = tmux("has-session", "-t", "=" + SESSION, check=False).returncode == 0
    if args.check:
        print(
            json.dumps(
                {
                    "tmux": SESSION,
                    "exists": exists,
                    "ownerAlive": alive,
                    "sessionId": config["sessionId"],
                    "autoResume": config.get("autoResume", False),
                    "wouldCreate": [
                        TMUX,
                        "new-session",
                        "-d",
                        "-s",
                        SESSION,
                        "-c",
                        config["cwd"],
                        *pane_command,
                    ],
                },
                indent=2,
            )
        )
        return 0
    with recovery.locked(state / "tmux-create.lock", nonblocking=True):
        exists = tmux("has-session", "-t", "=" + SESSION, check=False).returncode == 0
        if exists:
            tag = tmux("show-option", "-qv", "-t", SESSION, "@maistro_session_id").stdout.strip()
            if tag != config["sessionId"]:
                raise ValueError("Existing tmux session pi is not ours; it was not changed")
        else:
            if recovery.owner_alive(recovery.load_config(state).get("owner")):
                raise ValueError(
                    "Original Pi still running outside managed tmux; no duplicate started"
                )
            tmux(
                "new-session",
                "-d",
                "-s",
                SESSION,
                "-c",
                config["cwd"],
                *pane_command,
            )
            tmux("set-option", "-t", SESSION, "@maistro_session_id", config["sessionId"])
    if args.ensure:
        return 0
    if args.boot:
        # A foreground WSL client keeps the distro alive; this is event waiting,
        # not a polling loop or an automatic job/agent restart loop.
        return subprocess.call([TMUX, "wait-for", channel])
    action = "switch-client" if os.environ.get("TMUX") else "attach-session"
    return subprocess.call([TMUX, action, "-t", "=" + SESSION])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("maistro-pi-start: " + str(error), file=sys.stderr)
        sys.exit(1)
