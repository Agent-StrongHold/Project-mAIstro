#!/usr/bin/env python3
"""Observe named tmux foremen without killing sessions or injecting terminal input.

This is the fail-closed replacement for the interrupted wake-homies prototype.
A Pi process is liveness evidence only, not proof of task progress or permission
for an automatic restart. This observer never arms wake/relaunch; use foremen.py
only after identities and the message-delivery contract are registered.
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from .recovery_paths import TMUX

NAMES = ("pi", "maistro", "homie1")
FORMAT = "#{session_name}\t#{pane_id}\t#{pane_pid}\t#{pane_dead}"


def tmux_panes(tmux=TMUX, socket=None):
    command = [tmux]
    if socket:
        command += ["-L", socket]
    # Enumerate once and match complete names. '=pi' is a target-session
    # selector, not a safe target-pane selector for display-message.
    result = subprocess.run(
        [*command, "list-panes", "-a", "-F", FORMAT],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("tmux inventory unavailable: " + result.stderr.strip())
    panes = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            raise ValueError("invalid tmux pane inventory")
        name, pane, pid, dead = fields
        if not pane.startswith("%") or not pid.isdigit() or int(pid) <= 0 or dead not in ("0", "1"):
            raise ValueError("invalid tmux pane identity")
        panes.append({"session": name, "pane": pane, "pid": int(pid), "dead": dead == "1"})
    return panes


def processes(root=Path("/proc")):
    """Capture only liveness identities, never command-line arguments or secrets."""
    result = {}
    for directory in root.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            text = (directory / "stat").read_text()
            left, right = text.index("("), text.rindex(")")
            fields = text[right + 2 :].split()
            result[int(directory.name)] = {
                "comm": text[left + 1 : right],
                "state": fields[0],
                "parent": int(fields[1]),
                "start_ticks": fields[19],
            }
        except FileNotFoundError:
            # Exiting between enumeration and read is not a health proof.
            continue
    return result


def pi_descendants(pid, table):
    """Include Pi beneath a Python/shell launcher, excluding dead processes."""
    pending, seen, matches = [pid], set(), []
    children = {}
    for child, info in table.items():
        children.setdefault(info["parent"], []).append(child)
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        info = table.get(current)
        if info is None or info["state"] in ("Z", "X"):
            continue
        # The installed interactive Pi sets its process title to 'pi'.
        # Unknown/custom launchers fail closed instead of being called dead.
        if info["comm"] == "pi":
            matches.append(current)
        pending.extend(children.get(current, ()))
    return sorted(matches)


def assess(panes, table):
    rows = []
    for name in NAMES:
        members = [p for p in panes if p["session"] == name]
        live = [p for p in members if not p["dead"]]
        pids = sorted({pid for p in live for pid in pi_descendants(p["pid"], table)})
        if not members:
            state = "missing_session"
        elif not live:
            state = "dead_panes_preserved"
        elif any(p["pid"] not in table for p in live):
            state = "unknown_process_identity"
        elif len(pids) > 1:
            state = "multiple_pi_processes"
        elif pids:
            state = "pi_present"
        else:
            state = "no_pi_process"
        rows.append(
            {
                "session": name,
                "state": state,
                "panes": [p["pane"] for p in members],
                "pi_pids": pids,
            }
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read-only (the default)")
    parser.add_argument(
        "--socket", help="inspect an explicit tmux socket, e.g. an isolated test server"
    )
    args = parser.parse_args(argv)
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "mode": "read_only",
        "wake_armed": False,
        "progress_verified": False,
        "mutations": [],
    }
    try:
        report["sessions"] = assess(tmux_panes(socket=args.socket), processes())
        complete = all(row["state"] == "pi_present" for row in report["sessions"])
        report["all_named_pi_present"] = complete
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report["error"] = str(exc)
        complete = False
    print(json.dumps(report, indent=2))
    # Even when all processes exist, periodic wake and progress acknowledgement
    # are not verified by this observer. Never claim full wake/progress health.
    return 2


if __name__ == "__main__":
    sys.exit(main())
