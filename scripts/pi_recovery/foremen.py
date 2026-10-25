#!/usr/bin/env python3
"""Preserve named terminals; restore pinned Pi foremen and nudge via intercom.

No kill/respawn/send-keys operations. Unknown identity fails closed. Delivery is
not progress. Foremen own decisions; this process never performs GitHub work.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import check_foremen as health
from . import maistro_pi_resume as recovery
from .recovery_paths import FOREMEN_ROOT, INTERCOM_CLI, NODE, TMUX, bound_command

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = FOREMEN_ROOT
CLI = [NODE, str(INTERCOM_CLI)]
NAMES = ("maistro", "homie1")
PERIOD = 900


def run(argv, timeout=30, **kwargs):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kwargs)
    if p.returncode:
        raise RuntimeError(f"{argv[0]} failed ({p.returncode}): {p.stderr.strip()[:300]}")
    return p.stdout


def strict_true(value):
    """A JSON flag must be boolean true, not a truthy string or integer."""
    return isinstance(value, bool) and value


def object_output(argv, **kwargs):
    text = run(argv, **kwargs)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Command returned invalid JSON; no assumed success") from error
    if not isinstance(value, dict):
        raise ValueError("Command must return a JSON object")
    return value


def load(root):
    cfg = recovery.load_json(root / "config.json")
    if (
        not isinstance(cfg, dict)
        or cfg.get("version") != 1
        or set(cfg.get("roles", {})) != set(NAMES)
    ):
        raise ValueError("Incomplete foreman bindings")
    for name, role in cfg["roles"].items():
        import uuid

        uuid.UUID(role["session_id"])
        if not all(
            isinstance(role.get(k), str) and role[k] for k in ("provider", "model", "thinking")
        ):
            raise ValueError("Explicit provider/model/thinking required")
        if not (HERE / "foremen" / (name + ".md")).is_file():
            raise ValueError("Missing role brief")
    if cfg["roles"]["maistro"]["session_id"] == cfg["roles"]["homie1"]["session_id"]:
        raise ValueError("Foremen must have distinct identities")
    cwd = Path(cfg.get("cwd", str(Path.home()))).expanduser()
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError("Foreman cwd must be an existing absolute directory")
    cfg["cwd"] = str(cwd.resolve())
    return cfg


def read_optional(path):
    value = recovery.load_json(path) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected object in {path.name}")
    return value


def inventory():
    p = subprocess.run(
        [
            TMUX,
            "list-panes",
            "-a",
            "-F",
            "#{session_name}\t#{session_id}\t#{pane_id}\t#{pane_pid}\t#{pane_dead}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if p.returncode:
        # A missing server is distinct from an inaccessible/unknown server.
        text = p.stderr.strip()
        if text.startswith("no server running on ") or (
            text.startswith("error connecting to ") and text.endswith("(No such file or directory)")
        ):
            return []
        raise RuntimeError("Cannot inventory tmux; no action: " + text[:300])
    rows = []
    for line in p.stdout.splitlines():
        name, sid, pane, pid, dead = line.split("\t")
        if (
            not sid.startswith("$")
            or not pane.startswith("%")
            or not pid.isdigit()
            or dead not in ("0", "1")
        ):
            raise ValueError("Invalid tmux identity; no action")
        numeric_pid = int(pid)
        if numeric_pid <= 0:
            raise ValueError("Invalid pane PID; no action")
        rows.append(
            {
                "session": name,
                "session_id": sid,
                "pane": pane,
                "pid": numeric_pid,
                "dead": dead == "1",
            }
        )
    return rows


def observe(name, role, root, panes, table):
    members = [p for p in panes if p["session"] == name]
    owner = read_optional(root / name / "owner.json")
    alive = recovery.owner_alive(owner.get("process"))
    pi_pids = {
        pid for p in members if not p["dead"] for pid in health.pi_descendants(p["pid"], table)
    }
    if alive:
        if owner.get("session_id") != role["session_id"]:
            raise ValueError(f"{name}: live owner has another session identity")
        if owner["process"]["pid"] not in pi_pids:
            raise ValueError(
                f"{name}: owner alive outside named Pi panes; preserve, do not duplicate"
            )
        return "running"
    if pi_pids:
        raise ValueError(f"{name}: unregistered Pi already present; preserve, do not duplicate")
    if any(not p["dead"] and p["pid"] not in table for p in members):
        raise ValueError(f"{name}: unknown pane process; preserve")
    return "needs_window" if members else "needs_session"


def reserve_attempt(root, name, now):
    path = root / name / "launch-attempts.json"
    recent = [t for t in read_optional(path).get("times", []) if now - t < 86400]
    if len(recent) >= 3 or (recent and now - recent[-1] < PERIOD):
        raise ValueError(f"{name}: launch budget/backoff; owner attention required")
    recovery.save_json(path, {"times": [*recent, now]})


def start_command(root, name):
    return bound_command(
        [sys.executable, str(HERE / "cli.py"), "foremen", "--root", str(root), "launch", name],
        PI_FOREMEN_ROOT=str(root),
    )


def ensure_role(name, role, root, panes, table, now, cwd=None):
    state = observe(name, role, root, panes, table)
    if state == "running":
        return {"role": name, "state": state}
    reserve_attempt(root, name, now)  # commit attempt before the external effect
    command = shlex.join(start_command(root, name))
    members = [p for p in panes if p["session"] == name]
    if members:
        # New window, never replace the shell or a dead pane containing history.
        argv = [
            TMUX,
            "new-window",
            "-t",
            members[0]["session_id"] + ":",
            "-n",
            "foreman",
            "-P",
            "-F",
            "#{pane_id}",
            command,
        ]
    else:
        argv = [
            TMUX,
            "new-session",
            "-d",
            "-s",
            name,
            "-n",
            "foreman",
            "-c",
            cwd or str(Path.home()),
            "-P",
            "-F",
            "#{pane_id}",
            command,
        ]
    pane = run(argv).strip()
    if not pane.startswith("%"):
        raise ValueError(f"{name}: creation outcome unknown; inspect, do not repeat")
    return {"role": name, "state": "started_unverified", "pane": pane}


def launch(root, name, cfg):
    role = cfg["roles"][name]
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with recovery.locked(folder / "owner.lock", nonblocking=True):
        old = read_optional(folder / "owner.json")
        if recovery.owner_alive(old.get("process")):
            raise ValueError("Pinned Pi owner still alive; refusing duplicate")
        pane = os.environ.get("TMUX_PANE", "")
        if not pane.startswith("%"):
            raise ValueError("Foremen must start in their tmux pane")
        window = run([TMUX, "display-message", "-p", "-t", pane, "#{window_id}"]).strip()
        if not window.startswith("@"):
            raise ValueError("Cannot identify own window")
        run([TMUX, "set-option", "-w", "-t", window, "remain-on-exit", "on"])
        auth = object_output(
            [
                recovery.PI,
                "auth",
                "check",
                "--provider",
                role["provider"],
                "--model",
                role["model"],
                "--no-refresh",
                "--json",
            ]
        )
        if auth.get("status") != "ready":
            raise ValueError("Provider credentials not ready; no fallback")
        prompt = (
            f"Start/recover your approved {name} foreman role. Read your loaded role contracts. "
            f"Your exact session_id is {role['session_id']}; manifest {root / 'config.json'}; "
            f"write readiness/progress to {folder / 'status.json'}. "
            "First turn: read-only ownership/health reconciliation, readiness acknowledgement "
            "to primary Pi via intercom, and one proposed next step. No child launches, "
            "worktree mutation, service changes or GitHub mutation in this startup turn."
        )
        argv = [
            recovery.PI,
            "--session-id",
            role["session_id"],
            "--session-dir",
            str(folder / "sessions"),
            "--name",
            name,
            "--provider",
            role["provider"],
            "--model",
            role["model"],
            "--thinking",
            role["thinking"],
            "--append-system-prompt",
            str(HERE / "foremen/common.md"),
            "--append-system-prompt",
            str(HERE / "foremen" / (name + ".md")),
            "--",
            prompt,
        ]
        env = dict(os.environ)
        for key in ("PI_SESSION_ID", "PI_SESSION_FILE"):
            env.pop(key, None)
        child = subprocess.Popen(argv, cwd=cfg["cwd"], env=env)
        record = {
            "session_id": role["session_id"],
            "role": name,
            "pane": pane,
            "process": recovery.process_identity(child.pid),
            "started_at": recovery.now(),
        }
        recovery.save_json(folder / "owner.json", record)
        try:
            code = child.wait()
        except KeyboardInterrupt:
            code = child.wait()
        recovery.save_json(
            folder / "owner.json", {**record, "exit_code": code, "exited_at": recovery.now()}
        )
        return code


def valid_assignment(root, name, role, now):
    if name == "maistro":
        return True
    data = read_optional(root / name / "assignment.json")
    if (
        data.get("session_id") != role["session_id"]
        or not data.get("scope")
        or not data.get("authority")
    ):
        return False
    if not isinstance(data.get("expires_at"), str):
        return False
    try:
        expiry = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        return expiry.tzinfo is not None and expiry.timestamp() > now
    except (KeyError, TypeError, ValueError):
        return False


def roster(cwd=None):
    data = object_output(
        [*CLI, "list", "--name", "foreman-wake", "--json"], cwd=cwd or str(Path.home())
    )
    if not strict_true(data.get("ok")) or not isinstance(data.get("sessions"), list):
        raise ValueError("Intercom roster unavailable")
    return {row["id"]: row for row in data["sessions"]}


def poke(name, role, root, peers, now, cwd=None):
    peer = peers.get(role["session_id"])
    if not peer:
        return {"role": name, "wake": "not_connected"}
    if peer.get("status") != "idle":
        return {"role": name, "wake": "busy_or_unknown"}
    status = read_optional(root / name / "status.json")
    if status and status.get("session_id") != role["session_id"]:
        raise ValueError(f"{name}: stale/mismatched status identity")
    if status.get("mode") == "blocked":
        return {
            "role": name,
            "wake": "blocked",
            "reason": status.get("blocked_reason", "unspecified"),
        }
    if not valid_assignment(root, name, role, now):
        return {"role": name, "wake": "unassigned_idle"}
    path = root / name / "last-wake.json"
    previous = read_optional(path)
    if now - previous.get("attempted_at", 0) < PERIOD:
        return {"role": name, "wake": "deduplicated"}
    # Persist before sending: a crash after delivery must not immediately double-send.
    recovery.save_json(
        path, {"attempted_at": now, "session_id": role["session_id"], "delivery": "unknown"}
    )
    text = (
        "Scheduled foreman check: this is a nudge, NOT new authority. Continue your current "
        "authorized task or identify one concrete blocker/owned next action within your role. "
        "Do not replay old children or start a new campaign. Preserve worktrees and gates. "
        "Update your status.json with actual progress evidence or a precise blocked/idle reason; "
        "receiving this message is not progress. Escalate material blockers to primary pi."
    )
    receipt = object_output(
        [
            *CLI,
            "send",
            "--to",
            role["session_id"],
            "--name",
            "foreman-wake",
            "--text",
            text,
            "--json",
        ],
        cwd=cwd or str(Path.home()),
    )
    if not strict_true(receipt.get("ok")) or not strict_true(receipt.get("delivered")):
        raise ValueError(f"{name}: intercom did not confirm delivery")
    recovery.save_json(
        path,
        {
            "attempted_at": now,
            "session_id": role["session_id"],
            "receipt": receipt,
            "delivery": "delivered",
            "progress_verified": False,
        },
    )
    return {"role": name, "wake": "delivered", "progress_verified": False}


def progress_attention(root, name, role, now):
    status = read_optional(root / name / "status.json")
    if not status:
        return None  # Startup readiness is verified separately, not invented.
    if status.get("session_id") != role["session_id"]:
        return "status identity mismatch"
    if status.get("mode") == "blocked":
        return "blocked: " + str(status.get("blocked_reason", "unspecified"))[:240]
    if status.get("mode") != "working":
        return None
    try:
        at = datetime.fromisoformat(status["last_progress_at"].replace("Z", "+00:00"))
        if at.tzinfo is None:
            return "progress timestamp lacks timezone"
        age = now - at.timestamp()
    except (KeyError, TypeError, ValueError, AttributeError):
        return "progress timestamp missing/invalid"
    if age < -300:
        return "progress timestamp is in the future"
    return "self-reported progress stale >45min" if age > 2700 else None


def escalate(root, cfg, peers, report, now, cwd=None):
    problems = [
        row
        for row in report["roles"]
        if "error" in row or row.get("attention") or row.get("wake") in ("blocked", "not_connected")
    ]
    if not problems:
        return
    path = root / "last-alert.json"
    if now - read_optional(path).get("attempted_at", 0) < 3600:
        report["alert"] = "rate_limited"
        return
    operator = cfg.get("operator_session_id")
    if peers.get(operator, {}).get("status") != "idle":
        report["alert"] = "operator_busy_or_disconnected; see last-cycle.json"
        return
    recovery.save_json(path, {"attempted_at": now, "delivery": "unknown"})
    receipt = object_output(
        [
            *CLI,
            "send",
            "--to",
            operator,
            "--name",
            "foreman-wake",
            "--json",
            "--text",
            "Foreman attention needed (not authority to restart/kill): "
            + json.dumps(problems)[:2000],
        ],
        cwd=cwd or str(Path.home()),
    )
    if not strict_true(receipt.get("ok")) or not strict_true(receipt.get("delivered")):
        raise ValueError("Foreman attention delivery not confirmed")
    recovery.save_json(path, {"attempted_at": now, "receipt": receipt, "delivery": "delivered"})
    report["alert"] = "delivered_not_resolution"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "action", nargs="?", default="check", choices=("check", "ensure", "cycle", "launch")
    )
    parser.add_argument("name", nargs="?", choices=NAMES)
    args = parser.parse_args(argv)
    os.umask(0o077)
    root = args.root.expanduser().resolve()
    cfg = load(root)
    if args.action != "check" and not strict_true(cfg.get("enabled")):
        raise ValueError("Foreman recovery is not armed")
    if args.action == "launch":
        if not args.name:
            parser.error("launch requires a role")
        return launch(root, args.name, cfg)
    report = {"at": recovery.now(), "action": args.action, "roles": [], "progress_verified": False}
    if args.action == "check":
        panes, table = inventory(), health.processes()
        for name, role in cfg["roles"].items():
            report["roles"].append({"role": name, "state": observe(name, role, root, panes, table)})
    else:
        run_cycle(root, cfg, args.action, report)
    print(json.dumps(report, indent=2))
    incomplete = any(
        "error" in row
        or row.get("attention")
        or row.get("wake") in ("blocked", "not_connected")
        or (args.action == "check" and row.get("state") != "running")
        for row in report["roles"]
    )
    return 2 if incomplete else 0


def run_cycle(root, cfg, action, report):
    """Reconcile identities under the controller lock before any bounded effect."""
    with recovery.locked(root / "cycle.lock", nonblocking=True):
        panes, table = inventory(), health.processes()
        if not any(p["session"] == "pi" for p in panes):
            run([sys.executable, str(HERE / "cli.py"), "start", "--ensure"])
        # Roster failure must not become an invented empty peer registry.
        peers = roster(cfg["cwd"])
        for name, role in cfg["roles"].items():
            try:
                if (
                    role["session_id"] in peers
                    and observe(name, role, root, panes, table) != "running"
                ):
                    raise ValueError(
                        f"{name}: session connected outside owned pane; do not duplicate"
                    )
                row = ensure_role(name, role, root, panes, table, time.time(), cwd=cfg["cwd"])
                if row["state"] == "running":
                    attention = progress_attention(root, name, role, time.time())
                    if attention:
                        row["attention"] = attention
                if action == "cycle" and row["state"] == "running":
                    row.update(poke(name, role, root, peers, time.time(), cwd=cfg["cwd"]))
                report["roles"].append(row)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                report["roles"].append({"role": name, "error": str(error)})
        if action == "cycle":
            escalate(root, cfg, peers, report, time.time(), cwd=cfg["cwd"])
        recovery.save_json(root / "last-cycle.json", report)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(
            json.dumps({"at": recovery.now(), "error": str(error), "progress_verified": False}),
            file=sys.stderr,
        )
        sys.exit(2)
