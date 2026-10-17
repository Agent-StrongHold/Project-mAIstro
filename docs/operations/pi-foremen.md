# Optional Linux Pi foremen and saved-session recovery

This is operator tooling, **not** a Workspaces service or another fleet scheduler.
It versions a recovery mechanism and role contracts, not a particular person's
conversations. Checkout, import and test collection start nothing. `configure`
creates **disabled** bindings. Installation, arming, model calls, service changes
and publication each require the operator's approval; this PR is not a rollout.

## Roles and authority

| Terminal | Responsibility |
|---|---|
| `pi` | Existing human/control conversation, restored from its exact journal |
| `maistro` | Operations, ownership reconciliation and bounded stall diagnosis |
| `homie1` | One admitted repair and validation; idle when unassigned |

See `scripts/pi_recovery/foremen/{common,maistro,homie1}.md` and
[the shared context note](../../.cursor/context/pi-foremen-recovery.md).
Load context explicitly in a task prompt; `.cursor/context/` is not auto-injected.

Startup and timer messages grant no implementation, merge, enqueue, publication,
service or delegation authority. Existing worker/controller ownership remains
intact. One writer per isolated worktree; preserve dirty trees and interrupted
indexes. Agent briefs are **not an OS sandbox**. Run this only under a trusted
local account with reviewed Pi extensions and appropriate existing permissions.

## What is durable, and what is not

- Primary recovery registers the existing Pi journal, exact session ID, cwd,
  provider/model, handoff and boot/PID/start-tick ownership. It does not create a
  replacement conversation or retry old external effects.
- Atomic, checksummed checkpoints retain three journal generations and a task
  sidecar projected from the active parent chain, not abandoned branches.
  Legacy sidecars remain readable; corrupt lineage fails before replacement.
- An interrupted tail may yield a valid-prefix backup. Restoration goes into a
  **new** journal, preserves the original, and records its reason. Wrong identity,
  wrong hash, unsupported projection or a live owner fails closed.
- Foremen have separate native session journals, owner records, status, assignment
  and launch/wake receipts. They do **not** automatically inherit the primary's
  separate checksum-backup facility. These are not perfect clones of earlier roles.
- The local handoff and current external evidence govern continuation. Restore
  conversation context, then reconcile tasks, ownership, worktrees and remote
  effects before action. A pre-restart `running` task is interrupted/unknown.

**Keep outside Git:** credentials, private journals/handoffs, current IDs,
assignments/status, process/boot records, host evidence and backup snapshots.
Back those up privately with appropriate encryption/access controls. A fresh
clone alone cannot recreate private conversation history or credentials.

## Prerequisites and paths

Linux with `/proc`, Python 3.12+, tmux, Node, a reviewed Pi installation and
`pi-intercom` loaded into the interactive sessions. User systemd is optional.
The installed Pi must support explicit session identity, session directory,
provider/model selection and `pi auth check --no-refresh --json`. Verify version
and auth against your chosen route; **no silent provider/model fallback**.

Entry point (from a checkout):

```sh
python3 scripts/pi_recovery/cli.py --help
```

Commands: `configure`, `resume`, `start`, `foremen`, `observe`; `pane` is the
internal tmux wrapper. Use this entry point rather than executing modules with
relative imports as bare files.

Defaults and optional environment overrides (paths, **not secrets**):

| Variable | Default |
|---|---|
| `PI_RECOVERY_PI`, `PI_RECOVERY_TMUX`, `PI_RECOVERY_NODE` | Executables on PATH |
| `PI_CODING_AGENT_DIR` | `~/.pi/agent` |
| `PI_RECOVERY_STATE_DIR` | `~/.local/state/maistro-pi-resume` |
| `PI_FOREMEN_ROOT` | `~/.local/state/pi-foremen` |
| `PI_FOREMEN_INTERCOM_CLI` | `<agent-dir>/npm/node_modules/pi-intercom/cli.mjs` |
| `PI_RECOVERY_SESSION_MANAGER` | SDK module resolved from Pi; offline tests only |

Use absolute paths for overrides. Reviewed non-secret path bindings are carried
into tmux wrapper commands, since an existing server does not automatically
inherit a new client's arbitrary environment. No credential environment is
copied into command lines. Pi's existing credential configuration still applies.

## Manual enrollment (not an automatic installer)

Do not overwrite an accepted host installation from a moving Git branch. Review
and pin a revision, keep the current deployment and private state, and obtain
separate rollout authority. The following describes a **fresh**, approved setup;
existing sessions/services require an explicit migration review instead.

1. Copy the reviewed `scripts/pi_recovery/` directory to an absent operator-owned
   `~/.local/lib/pi_recovery/` (including briefs and package files). Preserve any
   existing destination; do not use a blind replacement command.
2. Write a private `RESUME.md` under the primary state directory. Record current
   goals, scopes, owners, artifact paths and stop conditions; exclude passwords.
3. From the **existing canonical Pi's bash tool**, register that conversation:

   ```sh
   python3 "$HOME/.local/lib/pi_recovery/cli.py" resume \
     --register-current --auto-resume \
     --handoff "$HOME/.local/state/maistro-pi-resume/RESUME.md"
   python3 "$HOME/.local/lib/pi_recovery/cli.py" resume --check
   ```

   Registration requires actual `PI_SESSION_ID`, `PI_SESSION_FILE`, provider,
   model and Pi process ancestry, not fabricated shell variables. Omit
   `--auto-resume` to reopen without an automatic continuation prompt. Never
   re-register over another canonical session's state merely to pass a check.
4. Inspect tmux identity/ownership. The launcher manages the session named `pi`
   and tag `@maistro_session_id`. It refuses an existing untagged/foreign session
   and never adopts or destroys it automatically. For manual adoption, the owner
   must first verify the exact live Pi ancestry/session ID, then explicitly set
   that tag on the matching terminal. Do not start a duplicate bare Pi.
5. Provision the two foremen with a real workspace and explicit route:

   ```sh
   python3 "$HOME/.local/lib/pi_recovery/cli.py" configure \
     --cwd /absolute/reviewed/workspace \
     --operator-session-id YOUR_EXISTING_PI_SESSION_ID \
     --provider YOUR_PROVIDER --model YOUR_MODEL --thinking medium
   ```

   This exclusively creates private `config.json`, with fresh distinct IDs and
   `enabled:false`; it refuses to replace existing bindings and launches nothing.
   Review the manifest/briefs, route availability and native intercom CLI before
   explicitly changing `enabled` to JSON boolean `true`. Never rotate live IDs
   to make an ownership error disappear.
6. With arming/launch authority, run **once**:

   ```sh
   python3 "$HOME/.local/lib/pi_recovery/cli.py" foremen ensure
   ```

   This may create windows and model calls. Inspect each startup acknowledgement,
   exact identity, owner and readiness artifact. `started_unverified` is not a
   success claim. The first model turn is read-only reconciliation. Do not repeat
   an ambiguous launch; inspect preserved panes and receipts first.
7. After this works, optionally install the four reviewed user-unit templates
   from `scripts/pi_recovery/systemd/`. Inspect existing units and refuse blind
   replacement. `EnvironmentFile=-%h/.config/pi-recovery.env` permits reviewed
   absolute path bindings (no `export`, no secrets). Only after explicit service
   approval, reload the user manager and enable the checkpoint/wake timers.
   Enable user lingering separately if pre-login user services are required.

No unit has an `ExecStop` that kills a Pi/tmux session. Do not restart a legacy
shell-creation service just because it appears inactive; inspect its `ExecStop`
first. A successful oneshot becoming inactive is normal, not a failed daemon.

## Wake and progress protocol

`foremen check` is read-only. `ensure` preserves shells/dead-pane history and adds
an absent owned role without attaching. `cycle` also nudges eligible idle peers
through native intercom. The optional timer runs at minutes 07/22/37/52 plus two
minutes after startup. It does no GitHub work, model reasoning or terminal typing.

- Complete tmux session enumeration and `/proc` identities, not a successful but
  empty `display-message -t '=pi'` result, determine role ownership.
- Unknown/duplicate/live-outside-pane identities fail closed. No kill, respawn,
  `send-keys`, fixed-sleep wake protocol or borrowed worker.
- Controller and per-role locks; at most three launch attempts per rolling day,
  with a 15-minute cooldown. Attempts are durable **before** external effects.
- Only a connected peer reporting `idle` is nudged. Busy/unknown/blocked peers are
  not interrupted. Homie1 additionally requires a matching, unexpired assignment.
- `working` with a missing/invalid or >45-minute-stale progress timestamp, blocked
  state and delivery errors are attention signals. Alerts to the operator are
  at most hourly and only when its exact identity is connected/idle; otherwise
  inspect `last-cycle.json`. Missing readiness is never invented as progress.
- Confirmed delivery is recorded with `progress_verified:false`. Ambiguous sends
  are not immediately repeated. Status files are self-reports, not acceptance.

Assignment shape (`<foremen-root>/homie1/assignment.json`, operator/maistro owned):

```json
{
  "session_id": "ACTUAL_MANIFEST_HOMIE1_ID",
  "scope": "Exact worktree/files, base SHA, validation and stop conditions",
  "authority": "Current owner admission, including any publication boundary",
  "expires_at": "REPLACE_WITH_FUTURE_UTC_ISO_TIMESTAMP"
}
```

Use real values; this placeholder is intentionally not an active assignment.
Close/expire completed assignments without deleting evidence. Valid assignment
text gates nudging, not OS capabilities or a substitute for actual authorization.

Read-only health checks / attachment:

```sh
python3 "$HOME/.local/lib/pi_recovery/cli.py" resume --check
python3 "$HOME/.local/lib/pi_recovery/cli.py" start --check
python3 "$HOME/.local/lib/pi_recovery/cli.py" foremen check
python3 "$HOME/.local/lib/pi_recovery/cli.py" observe --check
tmux attach -t pi                 # or maistro / homie1
```

`observe` is deliberately an observer, not a progress/repair verdict. Exit 2 or a
blocked/idle report may be an honest limit, not a reason to restart a process.
Inspect journals, status evidence and full current remote state before declaring
progress, delivery or a merge. Never manufacture a successful required status.

## Optional Windows → WSL boot and remote access

First validate Linux recovery manually. The intended chain is Windows boot →
distro-owner S4U task → Ubuntu WSL → user services → registered Pi in tmux.
OpenSSH/Tailscale installation, key enrollment, firewall policy and remote-device
acceptance are separate owner-controlled steps; these scripts do not install or
reconfigure them. Prefer key-based SSH over your approved private network.

`install-windows-boot.ps1` is an **optional manual** Administrator enrollment
helper. Supply the Windows account that owns the WSL distribution, distro name,
Linux user and absolute installed `cli.py` path. No machine/account is embedded.
It uses S4U (no stored password), a 30-second boot delay, bounded retries and
`start --boot`; it refuses any existing task with the same name and does not
start the task, kill processes, shut down WSL or reboot. Receipts go under the
user's local application data, never beside repository source. This helper uses
Linux's default state/PATH bindings; it does **not** source the user units'
`EnvironmentFile`. Non-default state or executable bindings require a separately
reviewed boot action, not an assumption that the systemd environment applies.

The foreground WSL client waits on an event channel, not a polling loop, to keep
the distro alive. Review actual boot/user-session/task evidence and verify the
**same saved Pi identity** through SSH after a separately authorized boot test.
The portable Windows helper has not been certified by a new live reboot here;
prior host-specific evidence does not certify new machines or these ported bytes.

## Validation and limits

Offline Python tests use synthetic journals, fake process/intercom/launch APIs
and uniquely named private tmux servers with dummy shells, never a live Pi or
shared tmux server. No model calls, GitHub writes, service changes or network
probes are part of them.

```sh
python3 -m unittest discover -v -s tests/pi_recovery
# In the isolated project development environment:
uv run pytest tests/pi_recovery -q -o addopts=''
uv run ruff check scripts/pi_recovery tests/pi_recovery
uv run ruff format --check scripts/pi_recovery tests/pi_recovery
```

Native tmux cases explicitly skip if tmux is unavailable; the native SessionManager
cold-load case requires Node plus an installed SDK (`PI_RECOVERY_SESSION_MANAGER`
can select it). Record skip counts and prerequisites: fake-only success is not
native integration proof. No test certifies arbitrary power loss, atomic remote
side effects, credentials remaining valid, perpetual progress or "never stalls."
Budget exhaustion, identity ambiguity, corrupt state, broker/auth outages and
real authorization blockers require owner attention, not automatic reset.
