"""Create fresh, DISABLED local foreman bindings; never start Pi or replace state."""

import argparse
import json
import os
import re
import uuid
from pathlib import Path

from .recovery_paths import FOREMEN_ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=FOREMEN_ROOT)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--operator-session-id", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--thinking",
        choices=("off", "minimal", "low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    args = parser.parse_args(argv)
    cwd = args.cwd.expanduser()
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError("cwd must be an existing absolute directory")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", args.operator_session_id):
        raise ValueError("Invalid operator session ID")
    if not args.provider.strip() or not args.model.strip():
        raise ValueError("Explicit provider and model required")
    config = {
        "version": 1,
        "enabled": False,
        "cwd": str(cwd.resolve()),
        "operator_session_id": args.operator_session_id,
        "authority": "Provisioned disabled. Startup/nudges grant no implementation or publication scope.",
        "roles": {
            name: {
                "session_id": str(uuid.uuid4()),
                "provider": args.provider,
                "model": args.model,
                "thinking": args.thinking,
            }
            for name in ("maistro", "homie1")
        },
    }
    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "config.json"
    # Exclusive creation preserves a prior installation, even across two initializers.
    # A torn first write fails JSON validation; it never becomes an armed setup.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"config": str(path), "enabled": False, "agents_started": 0}))
    return 0
