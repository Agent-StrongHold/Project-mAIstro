# Deployment Stance

## The guiding rule

> Official installs always include a sandbox worker.
> Hive is optional. UI is optional.
> Workerless execution is never supported in production.
> Partial/control-plane-only installs are source-only paths.

## Supported profiles

| Profile | Components | Use case |
|---------|-----------|----------|
| `full-ui` | maistro-server + sandbox-worker + Hive + persistence | Full deployment with dashboard |
| `full-headless` | maistro-server + sandbox-worker + persistence | API-only, no UI |
| `proxmox-vm` | maistro-server + sandbox-worker (separate VMs preferred) | Self-hosted on Proxmox |
| `docker-vps` | maistro-server + sandbox-worker + persistence | Single VPS with Docker/Podman |

## NOT supported by the installer

| Configuration | Reason | Path |
|---------------|--------|------|
| Serverless | No persistent sandbox worker | Source-install only |
| Workerless production | Violates security stance | Never |
| maistro-server only (no worker) | Untrusted code has nowhere safe to run | Dev/source only |
| Hive-only real runtime | Hive is not an execution engine | Dev/demo only |
| Control-plane only | Incomplete — no execution capability | Source-only |

## Sandbox ownership

- **Sandbox policy** (what isolation level is required) lives in `maistro-core`
- **Sandbox execution** (spawning/managing the isolated environment) lives in `maistro-sandbox-worker`
- **Sandbox display** (showing status to users) lives in Hive Conductor
- **Docker socket** is dev-only legacy, NEVER production

## Isolation tiers

### VM-grade (production for untrusted code)

| Backend | Notes |
|---------|-------|
| Kata Containers | Recommended first backend (mature, OCI-compatible) |
| Firecracker | Lightweight, fast cold-start |
| Hyperlight | For bounded/short-lived tool calls |

### Non-VM (acceptable for trusted/first-party code only)

| Backend | Notes |
|---------|-------|
| gVisor (runsc) | Syscall interception, no hardware VM needed |
| bubblewrap | User-namespace sandbox, no root |
| Rootless container | Podman rootless, no daemon |

### Forbidden in production

| Configuration | Why |
|---------------|-----|
| Host Docker socket mount | Effectively root on host |
| Bare subprocess | No isolation at all |
| `HIVE_MODE=demo` with real users | Demo mode has no security boundary |

## Installer preflight checks

The installer (`get.hiveconductor.dev`) verifies:

- [ ] `/dev/kvm` available (for VM backend) — warns if absent, suggests gVisor fallback
- [ ] Sandbox worker configured and reachable
- [ ] No Docker socket mounted into maistro-server container
- [ ] Auth enabled (`MAISTRO_ACCESS_TOKEN` set)
- [ ] Secrets generated (not defaults)
- [ ] Sandbox network denied by default
- [ ] Bind host is `127.0.0.1` unless explicitly overridden
