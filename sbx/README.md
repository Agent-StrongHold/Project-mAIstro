# Docker Sandboxes (`sbx`) kits for maistro

[Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) (`sbx`) run AI coding
agents inside isolated microVMs — each with its own kernel, filesystem, Docker
daemon, and deny-by-default egress. maistro uses `sbx` as the **execution
substrate**: opencode is one agent that can run on it, and the primary workload
is the **maistro-evolve RSI loop** (recursive self-improvement).

Each top-level directory here is a **kit** — a declarative `spec.yaml` (plus
optional `files/`) applied at sandbox creation, per the
[kit format](https://docs.docker.com/ai/sandboxes/customize/kits/).

## `maistro-rsi/` — run the RSI loop in a sandbox

A **mixin** kit: it layers the maistro toolchain (`maistro-core` / `-evolve` /
`-rsi`), a locked-down network contract, and `MAISTRO_RSI_SANDBOX=local` onto any
agent. Because `sbx` already provides the isolated microVM, the RSI runner uses
its **`LocalSandbox`** backend (runs directly on the mounted FS) instead of a
nested `DockerMicroVmSandbox` — no Docker-in-Docker.

```bash
# from a maistro-engine checkout (the codebase RSI improves)
sbx run opencode --kit ./sbx/maistro-rsi     # opencode + maistro RSI toolchain
sbx run claude   --kit ./sbx/maistro-rsi     # or any other agent
```

The mixin sets everything up; the RSI cycle itself is driven through
`maistro_rsi` (branch → patch → test → benchmark → Elo tournament → quarantine →
draft PR). The quarantine gate (Warden + adversarial review on sensitive-surface
diffs) still governs what may leave the sandbox as a PR.

Three subsystems compose to form the workload:

| Subsystem | Role in the cycle |
|-----------|-------------------|
| `maistro-core` | shared runtime |
| `maistro.builders` (in core) | spec → tests → code → review pipeline — **the code-modifying agent** (the cycle's `apply_patch`) |
| `maistro-evolve` / `maistro-rsi` | the loop + Elo tournament that branches, tests, benchmarks, and scores candidate vs. baseline |

The host agent you pass to `sbx run` (e.g. `opencode`) is optional — it is one
alternative `apply_patch` driver; the default self-modification agent is the
maistro builders pipeline.

### Model credentials

Do **not** paste API keys into the kit. Use `sbx`'s host-side secret proxy:
declare your provider under `network.serviceDomains` + `network.serviceAuth` in
`spec.yaml` (a commented Anthropic example is included) so the proxy injects the
auth header on the fly and the agent never sees the raw key.

### Backend selection outside `sbx`

`maistro_rsi.sandbox.create_rsi_sandbox()` reads `$MAISTRO_RSI_SANDBOX`:

| value | backend | when |
|-------|---------|------|
| `local` | `LocalSandbox` | already inside an `sbx` microVM (set by this kit) |
| `docker` (default) | `DockerMicroVmSandbox` | standalone / local dev |
