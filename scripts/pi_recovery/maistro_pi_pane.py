"""tmux pane entrypoint: recover one saved Pi session, then signal its boot client."""

import argparse
import subprocess
import sys
from pathlib import Path

from . import maistro_pi_resume as recovery
from .recovery_paths import TMUX


def prepare(state):
    config = recovery.load_config(state)
    reason = None
    try:
        recovery.read_journal(config["sessionFile"], config["sessionId"])
    except FileNotFoundError as error:
        reason = str(error)
    except ValueError as error:
        if "Session ID mismatch" in str(error):
            raise
        reason = str(error)
    if reason:
        _, _, checkpoint = recovery.checked_backup(state, config)
        recovery.save_json(
            state / "last-recovery.json",
            {
                "at": recovery.now(),
                "reason": reason,
                "originalPreserved": config["sessionFile"],
                "checkpointAt": checkpoint["savedAt"],
                "checkpointSha256": checkpoint["sha256"],
                "automaticJobReplay": False,
            },
        )
        print(
            "Journal incomplete/unavailable; restoring a verified checkpoint into a NEW file. Original preserved.",
            flush=True,
        )
    return bool(reason)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("channel")
    args = parser.parse_args(argv)
    recovery_args = ["--state-dir", str(args.state)]
    result = 1
    try:
        if prepare(args.state):
            recovery_args.append("--recover-backup")
        result = recovery.main(recovery_args)
    except (OSError, ValueError, RuntimeError) as error:
        print("Pi recovery failed: " + str(error), file=sys.stderr)
    finally:
        subprocess.run([TMUX, "wait-for", "-S", args.channel], check=False)
    return result
