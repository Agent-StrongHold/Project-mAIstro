#!/usr/bin/env python3
"""Durable, explicit Pi session resume. Never launches/replays workflow children."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .recovery_paths import PI, STATE

DEFAULT_STATE = STATE
DEFAULT_HANDOFF = DEFAULT_STATE / "RESUME.md"


def now():
    return datetime.now(UTC).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_json(path, value):
    atomic_write(path, (json.dumps(value, indent=2) + "\n").encode())


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except OSError as error:
        raise ValueError(f"Cannot read recovery metadata: {path}") from error


@contextmanager
def locked(path, nonblocking=False):
    try:
        with open(path, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
            yield
    except OSError as error:
        raise ValueError(f"Recovery lock unavailable: {path}") from error


def read_journal(path, sid=None, allow_partial=False):
    path = Path(path)
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("Journal exceeds backup size limit; original preserved")
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    entries, kept, dropped = [], [], 0
    for index, line in enumerate(lines):
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError("Session entries must be objects")
        except ValueError as error:
            if allow_partial and index == len(lines) - 1 and not line.endswith(b"\n"):
                dropped = len(line)
                break
            raise ValueError(f"Invalid journal line {index + 1}; original preserved") from error
        entries.append(entry)
        kept.append(line.rstrip(b"\r\n") + b"\n")
    if not entries or entries[0].get("type") != "session":
        raise ValueError("Missing Pi session header")
    header = entries[0]
    if not header.get("id") or not Path(header.get("cwd", "")).is_absolute():
        raise ValueError("Invalid session identity/cwd")
    if sid is not None and header["id"] != sid:
        raise ValueError("Session ID mismatch; refusing another session")
    if not allow_partial and not raw.endswith(b"\n"):
        raise ValueError("Unterminated journal tail; use --recover-backup, original preserved")
    return b"".join(kept), entries, dropped


def active_branch(entries):
    """Walk the persisted leaf to its root; never replay an abandoned branch."""
    nodes = [entry for entry in entries if entry.get("type") != "session"]
    if not nodes:
        return []
    by_id = {}
    for entry in nodes:
        ident = entry.get("id")
        if not isinstance(ident, str) or not ident or ident in by_id:
            raise ValueError("Invalid task lineage: missing or duplicate entry ID")
        by_id[ident] = entry
    ident = nodes[-1]["id"]
    branch, seen = [], set()
    while ident is not None:
        if not isinstance(ident, str) or not ident or ident not in by_id or ident in seen:
            raise ValueError("Invalid task lineage: missing or cyclic parent")
        entry = by_id[ident]
        if "parentId" not in entry:
            raise ValueError("Invalid task lineage: missing parentId")
        seen.add(ident)
        branch.append(entry)
        ident = entry["parentId"]
    return list(reversed(branch))


def task_snapshot(entries):
    """Reconstruct confirmed todo operations on the active branch only."""
    calls, tasks = {}, {}
    for entry in active_branch(entries):
        message = entry.get("message", {})
        content = message.get("content", [])
        if message.get("role") == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") == "toolCall" and block.get("name") in (
                    "todo",
                    "functions.todo",
                ):
                    calls[block["id"]] = block.get("arguments", {})
        if message.get("role") != "toolResult" or message.get("isError"):
            continue
        args = calls.pop(message.get("toolCallId"), None)
        if not args:
            continue
        text = (
            "\n".join(x.get("text", "") for x in content if isinstance(x, dict))
            if isinstance(content, list)
            else str(content)
        )
        apply_task_operation(tasks, args, text)
    return list(tasks.values())


def apply_task_operation(tasks, args, text):
    """Apply an already-matched, successful tool result to the task projection."""
    action = args.get("action")
    if action == "clear":
        tasks.clear()
    elif action == "create":
        match = re.search(r"Created #(\d+)", text)
        if match:
            try:
                ident = int(match.group(1))
            except ValueError as error:
                raise ValueError("Invalid confirmed task ID") from error
            tasks[ident] = {
                "id": ident,
                "status": "pending",
                **{k: v for k, v in args.items() if k not in ("action", "id")},
            }
    elif action in ("update", "delete") and args.get("id") in tasks:
        task = tasks[args["id"]]
        task.update(
            {
                k: v
                for k, v in args.items()
                if k not in ("action", "id", "addBlockedBy", "removeBlockedBy")
            }
        )
        deps = set(task.get("blockedBy", [])) | set(args.get("addBlockedBy", []))
        task["blockedBy"] = sorted(deps - set(args.get("removeBlockedBy", [])))
        if action == "delete":
            task["status"] = "deleted"


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def process_identity(pid):
    try:
        data = (Path("/proc") / str(pid) / "stat").read_text()
    except FileNotFoundError:
        return None
    try:
        tail = data[data.rfind(")") + 2 :].split()
        return {
            "pid": int(pid),
            "startTicks": tail[19],
            "bootId": boot_id(),
            "comm": data[data.find("(") + 1 : data.rfind(")")],
            "parent": int(tail[1]),
        }
    except ValueError as error:
        raise ValueError("Cannot verify process identity") from error
    except IndexError as error:
        raise ValueError("Incomplete process identity") from error


def owner_alive(owner):
    if not owner or owner.get("bootId") != boot_id():
        return False
    actual = process_identity(owner["pid"])
    return bool(actual and actual["startTicks"] == owner.get("startTicks"))


def ancestor_pi():
    pid = os.getppid()
    for _ in range(16):
        info = process_identity(pid)
        if not info:
            break
        if info["comm"] == "pi":
            return info
        if info["parent"] <= 1:
            break
        pid = info["parent"]
    raise ValueError("Cannot identify owning Pi process; register from its bash tool")


def register(state, handoff, auto_resume=False):
    session = os.environ.get("PI_SESSION_FILE")
    sid = os.environ.get("PI_SESSION_ID")
    if not session or not sid:
        raise ValueError("Register from Pi's bash tool; session metadata is required")
    _, entries, _ = read_journal(session, sid, allow_partial=True)
    if not handoff.is_file():
        raise ValueError("Recovery handoff file missing")
    config = {
        "version": 1,
        "sessionFile": str(Path(session).resolve()),
        "sessionId": sid,
        "cwd": entries[0]["cwd"],
        "provider": os.environ.get("PI_PROVIDER"),
        "model": os.environ.get("PI_MODEL"),
        "handoff": str(handoff.resolve()),
        "owner": ancestor_pi(),
        "registeredAt": now(),
        "autoResume": auto_resume,
    }
    if not config["provider"] or not config["model"]:
        raise ValueError("Explicit model/provider metadata required; no silent fallback")
    save_json(state / "config.json", config)
    return config


def load_config(state):
    config = load_json(state / "config.json")
    required = ("sessionId", "sessionFile", "cwd", "handoff", "provider", "model")
    if config.get("version") != 1 or any(
        not isinstance(config.get(k), str) or not config[k] for k in required
    ):
        raise ValueError("Unsupported or incomplete recovery configuration")
    return config


def checkpoint(state, config):
    data, entries, dropped = read_journal(
        config["sessionFile"], config["sessionId"], allow_partial=True
    )
    # Validate ancestry before writing any replacement checkpoint artifacts.
    tasks = task_snapshot(entries)
    digest = sha(data)
    blob = state / "snapshots" / (digest + ".jsonl")
    if not blob.exists():
        atomic_write(blob, data)
    elif sha(blob.read_bytes()) != digest:
        raise ValueError("Existing snapshot integrity mismatch")
    # Flush the source journal too, without changing any bytes.
    try:
        with open(config["sessionFile"], "rb") as stream:
            os.fsync(stream.fileno())
    except OSError as error:
        raise ValueError("Cannot flush source journal; checkpoint not committed") from error
    # Separate namespace preserves the pre-fix all-branches sidecar for the
    # same journal bytes. Never invalidate an old checkpoint mid-upgrade.
    task_blob = state / "snapshots" / (digest + ".active.tasks.json")
    save_json(task_blob, tasks)
    record = {
        "version": 1,
        "savedAt": now(),
        "sessionId": config["sessionId"],
        "source": config["sessionFile"],
        "snapshot": str(blob),
        "sha256": digest,
        "taskSnapshot": str(task_blob),
        "taskSha256": sha(task_blob.read_bytes()),
        "entries": len(entries),
        "taskCount": len(tasks),
        "taskProjection": "active-branch-v1",
        "incompleteTailBytesSkipped": dropped,
    }
    save_json(state / "checkpoint.json", record)
    # Retain three complete generations; never prune original sessions or worktrees.
    generations = sorted(blob.parent.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    keep = {blob, *[p for p in generations if p != blob][:2]}
    for old in generations:
        if (
            old not in keep
            and re.fullmatch(r"[0-9a-f]{64}\.jsonl", old.name)
            and not old.is_symlink()
        ):
            old.unlink()
            old.with_suffix(".tasks.json").unlink(missing_ok=True)
            old.with_suffix(".active.tasks.json").unlink(missing_ok=True)
    return record


def checked_backup(state, config):
    record = load_json(state / "checkpoint.json")
    snapshot = Path(record["snapshot"])
    if snapshot.parent != state / "snapshots" or snapshot.name != record["sha256"] + ".jsonl":
        raise ValueError("Invalid snapshot path")
    data, entries, _ = read_journal(snapshot, config["sessionId"])
    if sha(snapshot.read_bytes()) != record["sha256"]:
        raise ValueError("Snapshot checksum mismatch")
    projection = record.get("taskProjection", "all-entries-v0")
    suffixes = {"all-entries-v0": ".tasks.json", "active-branch-v1": ".active.tasks.json"}
    if projection not in suffixes:
        raise ValueError("Unsupported task snapshot projection")
    tasks = Path(record["taskSnapshot"])
    if (
        tasks != snapshot.with_suffix(suffixes[projection])
        or sha(tasks.read_bytes()) != record["taskSha256"]
    ):
        raise ValueError("Task snapshot checksum mismatch")
    return data, entries, record


def command(config, session):
    recovery = (
        "This session has been reopened. Before continuing, read "
        + config["handoff"]
        + ". Treat pre-reboot running jobs as interrupted/unknown, not complete or authorized to replay. "
        "Inspect durable task snapshots and artifacts, then reconcile worktrees and current remote state. "
        "Preserve all work. Do not blindly restart children, push, merge, enable auto-merge, or undo remote effects. "
        "Do not borrow team workers or launch extra reviewers. This startup grants no new publication authority."
    )
    argv = [
        PI,
        "--session",
        str(session),
        "--provider",
        config["provider"],
        "--model",
        config["model"],
        "--append-system-prompt",
        recovery,
    ]
    if config.get("autoResume"):
        argv += [
            "--",
            "Recover this saved session after restart. Read the handoff and latest durable task snapshot first. "
            "Reconcile interrupted work without replaying old commands. Continue the user's unfinished authorized "
            "goals according to the current handoff. Work locally; do not divert team workers or spawn "
            "extra reviewers. Preserve existing worktrees. If blocked on authorization, credentials, or real "
            "external state, report the blocker and wait. Do not launch another campaign merely because this "
            "session restarted. Do not claim pending gates or unfinished work complete.",
        ]
    return argv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--handoff", type=Path, default=DEFAULT_HANDOFF)
    parser.add_argument(
        "--auto-resume",
        action="store_true",
        help="with --register-current: resume saved goals automatically on a NEW Pi start",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--register-current", action="store_true")
    modes.add_argument("--checkpoint", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--recover-backup",
        action="store_true",
        help="explicitly restore a verified checkpoint to a NEW journal; preserve original",
    )
    args = parser.parse_args(argv)
    os.umask(0o077)
    state = args.state_dir.expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.recover_backup and (args.register_current or args.checkpoint):
        parser.error("--recover-backup is a resume/check option")
    if args.register_current or args.checkpoint:
        with locked(state / "checkpoint.lock"):
            config = (
                register(state, args.handoff, args.auto_resume)
                if args.register_current
                else load_config(state)
            )
            print(json.dumps(checkpoint(state, config), indent=2))
        return 0
    config = load_config(state)
    if not Path(config["cwd"]).is_dir() or not Path(config["handoff"]).is_file():
        raise ValueError("Recovery cwd or handoff missing")
    alive = owner_alive(config.get("owner"))
    if args.recover_backup:
        data, entries, record = checked_backup(state, config)
        selected = state / "recovered" / (str(uuid.uuid4()) + ".jsonl")
    else:
        data, entries, _ = read_journal(config["sessionFile"], config["sessionId"])
        selected = Path(config["sessionFile"])
        record = load_json(state / "checkpoint.json")
    if entries[0]["cwd"] != config["cwd"]:
        raise ValueError("Session cwd mismatch")
    plan = {
        "sessionId": config["sessionId"],
        "sessionFile": str(selected),
        "cwd": config["cwd"],
        "ownerAlive": alive,
        "checkpointAt": record["savedAt"],
        "recoverBackup": args.recover_backup,
        "launchCommand": command(config, selected),
        "automaticJobReplay": False,
    }
    if args.check:
        print(json.dumps(plan, indent=2))
        return 0
    if alive:
        raise ValueError("This Pi session is still running; refusing a duplicate writer")
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Resume requires an interactive terminal (or --dry-run)")
    return launch_saved(state, config, selected, data, args.recover_backup)


def launch_saved(state, config, selected, data, recover_backup):
    """Hold both ownership boundaries before starting the exact saved session."""
    with locked(state / "launch.lock", nonblocking=True):
        with locked(state / "checkpoint.lock"):
            current = load_config(state)
            if current != config or owner_alive(current.get("owner")):
                raise ValueError("Recovery ownership changed; retry after checking the session")
            if recover_backup:
                atomic_write(selected, data)
            else:
                checkpoint(state, config)
            print(
                "Reopening the saved conversation only. Interrupted jobs are NOT replayed.",
                flush=True,
            )
            child = subprocess.Popen(command(config, selected), cwd=config["cwd"])
            config.update(
                sessionFile=str(selected), owner=process_identity(child.pid), lastResumeAt=now()
            )
            save_json(state / "config.json", config)
        try:
            return child.wait()
        except KeyboardInterrupt:
            return child.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("maistro-pi-resume: " + str(error), file=sys.stderr)
        sys.exit(1)
