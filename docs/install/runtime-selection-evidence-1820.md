# Runtime-selection and host-privilege evidence (#1820)

Sanitized clean-account transcripts for the support matrix in
[`default-installer.md`](default-installer.md) ("Container runtime selection
and host privilege"). The issue's closure evidence asks for OS/runtime
versions, host identity/privilege mode, selected context, artifact revision,
ownership checks, and successful restart/recovery per claimed profile; this
file is that record. Secrets (`.env` values, API keys) are never printed by
the installer and do not appear here.

## Environment record

| Fact | Value |
|---|---|
| Host | WSL2 VM, Ubuntu 26.04 LTS, kernel `6.18.33.1-microsoft-standard-WSL2`, amd64 |
| Podman | 5.7.0 (rootless, invoked account's own store) |
| Compose provider | `docker-compose-v2` 2.40.3 (`podman compose` → `/usr/libexec/docker/cli-plugins/docker-compose`) |
| Docker | 29.1.3, Compose v2.39.1 (admin-managed daemon, socket `root:docker 0660`) |
| Python (host) | 3.14.4 |
| Artifact revision | `3f215bba723d469499b40b415e6e22ceaf7c1709` (branch `auto-1820`) |
| Clean account | `maistro-clean`, uid 1001, groups: `maistro-clean` only — no `docker`, no `sudo` |
| Ordinary account | `dev`, uid 1000, non-root, `docker` group membership **pre-granted by admin** (the one-time prerequisite the Docker-Engine row documents; the installer ran no `usermod`) |

Rootless podman prerequisites were satisfied exactly as the matrix states:
`podman`/`docker-compose-v2` installed once by an administrator
(`sudo apt-get install`), then the ordinary account enabled its own user
service (`systemctl --user start podman.socket`; user lingering enabled once
by the admin so the socket survives logout). No step of the install itself
required elevation for this profile.

## Profile 1 — Linux (WSL2 distro), rootless Podman, zero-admin install

Selected context: `MAISTRO_CONTAINER_RUNTIME=podman` (the wizardless
gap-fill), `MAISTRO_SKIP_WIZARD=1`. Delivery: source build. Every command ran
as `maistro-clean`.

### Discovery sequence (runs 1–5, revision `9d60eab60` + the healthcheck fix that became `3f215bba7`)

Interruption/retry behavior surfaced three real, distinct, actionable
failures before success — each re-run resumed on cached artifacts with
ownership preserved:

1. `MAISTRO_START_STACK=0` run: manifest written with
   `"container_runtime": "podman"`, `.env` generated (0600),
   `RECOVERY.md` written naming `podman compose`. Exposed the first in-lane
   finding: recovery text must name the selection (fixed in `9d60eab60`).
   The run ended at `install_cli` (`/usr/bin/python3: No module named pip`)
   — a pre-existing uv/pip bootstrap limitation on a pip-less account,
   unrelated to runtime selection; later runs set `MAISTRO_INSTALL_CLI=0`.
2. Full start failed: `rootlessport listen tcp 127.0.0.1:5433: bind:
   address already in use` — an unrelated admin-daemon stack on the shared
   host already publishes 5433. Remedy by the account itself (no elevation):
   `docker-compose.override.yml` remapping published host ports plus
   `MAISTRO_PORT`/`HIVE_PORT` in `.env` — the supported #405 operator
   mechanisms.
3. Same shape on `127.0.0.1:3100` (langfuse) — override extended.
4. All containers started; `maistro-engine` stuck **unhealthy**:
   `SyntaxError: Expected one or more names after 'import'` on every probe.
   Root cause: podman's compose provider word-splits exec-form healthcheck
   args, so `["CMD", "python", "-c", "import urllib…"]` reached the engine
   as `python -c import …`. The engine was serving the whole time
   (uvicorn logs healthy). Fixed in `3f215bba7` by moving the engine and
   conductor probes to the quoted CMD-SHELL form (validated against both
   runtimes' `config` render).
5. Full success: `[ok] Compose runtime: podman compose`, rendered config
   validated, `Engine healthy.` / `Conductor healthy.`, exit 0.

### Confirmation run at exactly `3f215bba7` (fresh clone of the revision)

```console
$ git rev-parse HEAD
3f215bba723d469499b40b415e6e22ceaf7c1709
$ ./install.sh            # MAISTRO_SKIP_WIZARD=1 MAISTRO_CONTAINER_RUNTIME=podman …
[ok] Compose runtime: podman compose
[ok] Rendered Compose config validated before startup.
[ok] Engine healthy.
[ok] Conductor healthy.
maistro-engine is ready
  Logs:  podman compose -f docker-compose.yml -f docker-compose.override.yml logs -f maistro-engine
  Stop:  podman compose -f docker-compose.yml -f docker-compose.override.yml down
```

Docker-only validations (engine API floor, credential-helper probe,
docker.sock discovery) did not run — an old Docker daemon is present on this
host and never got the chance to fail the Podman install.

### Fresh-login lifecycle, restart, ownership, teardown

From a new login shell (`bash -l`, fresh environment):

```console
$ whoami; id -Gn
maistro-clean
maistro-clean
$ podman compose -f docker-compose.yml -f docker-compose.override.yml ps
maistro-postgres        Up 10 minutes (healthy)
maistro-engine          Up 51 seconds
maistro-hive-conductor  Up 39 seconds
…                       # langfuse, litellm
$ … restart maistro-engine hive-conductor   # service restart from the new login
$ curl -sf http://127.0.0.1:18000/health/live
{"status":"ok"}
$ stat -c "%U:%G %a %n" .maistro-install .env docker-compose.override.yml
maistro-clean:maistro-clean 755 .maistro-install
maistro-clean:maistro-clean 600 .env
maistro-clean:maistro-clean 644 docker-compose.override.yml
$ stat -c "%U:%G" ~/.local/share/containers/storage/volumes
maistro-clean:maistro-clean
$ find . -user root | wc -l      # zero root-owned artifacts
0
$ … down --remove-orphans        # teardown per RECOVERY.md — clean exit
```

Named volumes, installer state, plan artifacts, and credentials all stayed
owned by the invoking account across every interruption and re-run.

## Profile 2 — Linux (WSL2 distro), Docker Engine, one-time admin prerequisite

Host identity: `dev`, uid 1000, non-root; daemon access via the
admin-granted `docker` group (root-equivalent — the matrix documents this and
the installer never adds it). Selected context: `MAISTRO_CONTAINER_RUNTIME=
docker`, wizardless, source build.

```console
$ ./install.sh
[ok] Compose runtime: docker compose
[ok] Docker Engine API 1.52 meets the required minimum 1.44.
[ok] Rendered Compose config validated before startup.
[ok] Engine healthy.
[ok] Conductor healthy.
maistro-engine is ready
```

Notable transcript moments, all before mutation or exactly at the gate that
owns them:

- The #405 override-safety gate refused a group-writable operator override
  with its exact remedy (`chmod go-w`), and the re-run proceeded — elevation
  and file-safety decisions happen *before* any stack mutation.
- A container-name collision with an unrelated stack on the shared daemon
  (`Conflict. The container name "/maistro-postgres" is already in use`) was
  resolved by the account itself via the same supported override file.
- Lifecycle from the account: `ps` (all healthy) → `restart` → engine health
  `{"status":"ok"}` → `down --remove-orphans` teardown, exit 0. State owned
  `dev:dev` (uid 1000); no root-owned artifacts; the account's group
  membership is unchanged by the install.

## Profile 3 — boundary: Docker selection from an account the daemon refuses

The adversarial setup the issue names: docker CLI on `PATH`, daemon socket
inaccessible (`root:docker 0660`, account not in the group), **and a fully
working rootless Podman** that a silent switch would hand the install to.

```console
$ docker info >/dev/null 2>&1 || echo "daemon NOT accessible"
daemon NOT accessible
$ podman info >/dev/null 2>&1 && echo "podman answers: yes"
podman answers: yes
$ ./install.sh        # MAISTRO_CONTAINER_RUNTIME=docker
[warn] The docker CLI is installed but the daemon is not responding.
[maistro] Waiting for the Docker daemon to become ready...
[warn] Could not start the Docker daemon. Start it manually (e.g. 'sudo service docker start'), then re-run.
[error] The container runtime docker is installed but does not answer as this account. The installer never switches to another runtime to proceed. Start it (or fix its socket permissions for this user), then re-run ./install.sh.
$ grep container_runtime .maistro-install/install-manifest.json
  "container_runtime": "docker",
$ id -Gn                              # no docker-group mutation
maistro-clean
$ find . -user root | wc -l           # no root-owned artifacts
0
```

The manifest records the honored selection even in failure; the working
Podman was never probed into service. (Wart, recorded honestly: the
unsupervised-daemon fallback prints a raw `Permission denied` for
`/var/log/dockerd.log` before waiting ~2 minutes on an account that could
never start dockerd. The final report is still the correct, recoverable one.)

## Findings that changed code in this round

| Finding (from the transcripts above) | Fix |
|---|---|
| `--no-start` runs left `COMPOSE_CMD` empty, so `RECOVERY.md`/`print_success` printed the `docker compose` literal for a Podman install | `9d60eab60` — `compose_line_cmd()` prefers the resolved front-end, else the selection's own CLI probe, else the selection literally |
| Exec-form healthchecks word-split under podman's compose provider; engine stuck "unhealthy", conductor dependency never starts | `3f215bba7` — engine/conductor probes moved to quoted `CMD-SHELL`; both runtimes' `config` render validated; pinned by test |
| With real `podman` on the dev host, the harness's "podman absent" tests measured the host binary | `3f215bba7` — hermetic PATH (shim dir + coreutils toolbin) |

## Not exercised in this lane (UNVERIFIED, machine-bound)

- **macOS rows** (Colima zero-admin, Docker Desktop one-time-admin): no
  macOS host. The matrix entries stay design claims.
- **Windows-side elevation flows** (`get.ps1` WSL2 feature enablement,
  reboot-resume): the transcripts run *inside* the WSL2 distro, which is the
  Linux side of that row; the Windows elevation choreography was not run.
- **Real GUI re-login**: "new shell/login" evidence uses a login shell
  (`bash -l`) with a fresh environment, not a desktop session.
- **`maistro upgrade` end-to-end from the clean account**: the upgrade
  manifest-recording contract is pinned by unit tests
  (`packages/maistro-core/tests/cli/test_upgrade.py`), but the clean account
  could not install the `maistro` CLI (host python lacks pip for the uv
  bootstrap) so a live upgrade was not recorded.

## Reproduction sketch

```bash
# one-time admin
sudo apt-get install -y podman docker-compose-v2
sudo useradd -m -s /bin/bash <clean-user> && sudo loginctl enable-linger <clean-user>
# as the clean user
systemctl --user start podman.socket
git clone <bundle-or-remote> maistro && cd maistro && git checkout <rev>
MAISTRO_SKIP_WIZARD=1 MAISTRO_CONTAINER_RUNTIME=podman ./install.sh
```
