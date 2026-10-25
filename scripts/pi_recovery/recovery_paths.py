"""Host-local paths for the optional Linux Pi recovery tools.

Environment overrides select installed executables, never credentials. Importing
this module neither creates state nor launches processes. Keep live state out of
Git; the repository contains templates and code, not an operator's conversation.
"""

import os
import shutil
from pathlib import Path


def executable(variable, name):
    return os.environ.get(variable) or shutil.which(name) or name


PI = executable("PI_RECOVERY_PI", "pi")
TMUX = executable("PI_RECOVERY_TMUX", "tmux")
NODE = executable("PI_RECOVERY_NODE", "node")
STATE = Path(
    os.environ.get("PI_RECOVERY_STATE_DIR", Path.home() / ".local/state/maistro-pi-resume")
).expanduser()
FOREMEN_ROOT = Path(
    os.environ.get("PI_FOREMEN_ROOT", Path.home() / ".local/state/pi-foremen")
).expanduser()
AGENT_DIR = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent")).expanduser()
INTERCOM_CLI = Path(
    os.environ.get("PI_FOREMEN_INTERCOM_CLI", AGENT_DIR / "npm/node_modules/pi-intercom/cli.mjs")
).expanduser()


def bound_command(argv, **overrides):
    """Carry non-secret path bindings across an already-running tmux server.

    tmux does not inherit arbitrary environment variables from each new client.
    Pass only these reviewed path settings, not the caller's full environment.
    """
    bindings = {
        "PI_RECOVERY_PI": PI,
        "PI_RECOVERY_TMUX": TMUX,
        "PI_RECOVERY_NODE": NODE,
        "PI_RECOVERY_STATE_DIR": str(STATE),
        "PI_FOREMEN_ROOT": str(FOREMEN_ROOT),
        "PI_CODING_AGENT_DIR": str(AGENT_DIR),
        "PI_FOREMEN_INTERCOM_CLI": str(INTERCOM_CLI),
        **overrides,
    }
    return [
        shutil.which("env") or "/usr/bin/env",
        *[f"{k}={v}" for k, v in bindings.items()],
        *argv,
    ]


def session_manager_path():
    """Optional offline SDK test dependency; a missing install is not emulated."""
    override = os.environ.get("PI_RECOVERY_SESSION_MANAGER")
    if override:
        return Path(override).expanduser()
    # An npm-installed Pi executable resolves to <package>/dist/cli.js.
    return Path(PI).resolve().parent / "core/session-manager.js"
