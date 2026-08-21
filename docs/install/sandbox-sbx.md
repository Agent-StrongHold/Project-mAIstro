# Running builders / evolve / RSI inside Docker Sandboxes (sbx)

Docker Sandboxes (`sbx`) gives each sandbox a hardware-isolated microVM
(KVM on Linux, Hypervisor.framework on macOS, Windows Hypervisor Platform on
Windows) with its own private Docker daemon and deny-by-default network
egress enforced by a host-side proxy. This page sets up a sandbox where the
maistro toolchain — `maistro builders`, `maistro-evolve`, and `maistro-rsi` —
runs against a repo with exactly two egress destinations: **GitHub** and
**your external LiteLLM gateway**.

Security posture, by construction:

- **Provider API keys never enter the sandbox.** The sandbox carries only a
  LiteLLM **virtual key** — scoped, budgeted, revocable — issued by a gateway
  running *outside* the sandbox.
- **No registry egress at runtime.** The images RSI's nested test containers
  need are preseeded into the template at build time and `docker load`ed into
  the private daemon at first boot.
- **PRs never leave unscanned.** `maistro-rsi run --open-prs` refuses to run
  unless the Warden-backed quarantine gate constructs successfully, and every
  diff is scanned (sensitive-surface diffs additionally require adversarial
  review) before a PR opens.
- Nested test containers run `--network=none` with a sanitized environment
  (no LITELLM_*/GITHUB_TOKEN), and the builders agent's subprocesses get a
  minimal env with no credentials at all.

## 1. Issue a virtual key on your LiteLLM gateway

On the machine running LiteLLM (e.g. the maistro-engine compose stack):

```bash
curl -s http://<litellm-host>:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key_alias": "sbx-rsi", "max_budget": 25.0}'
```

Keep the returned `sk-...` value; that is the only credential the sandbox gets.

## 2. Build the template + preseed images

On a machine with a Docker daemon (this step has registry egress; sandboxes
won't):

```bash
./deploy/sbx/build.sh                          # build + `sbx template load`
# or: PUSH_TAG=you/maistro-sbx:v1 ./deploy/sbx/build.sh   # push to a registry
```

This produces:
- `maistro-sbx-template:latest` — the sandbox template
  (`docker/sandbox-templates:shell-docker` + git/gh/python + the maistro
  packages + preseed tars),
- `preseed/python-3.12-slim.tar` and `preseed/maistro-engine-tests.tar` —
  loaded into each sandbox's private daemon at first boot.
  `maistro-engine-tests` carries a uv cache warmed from this repo's `uv.lock`
  so `uv sync --frozen --offline` works inside the offline test containers.

## 3. Configure and create the sandbox

```bash
# Point the kit at your gateway (must be a host:port the sbx proxy can route
# to — a LAN hostname/IP works; "localhost" inside the VM is the VM, not your
# host, so use a real address):
sed -i 's/LITELLM_HOST_PLACEHOLDER/litellm.lan:4000/' deploy/sbx/kit/spec.yaml

sbx kit validate ./deploy/sbx/kit
sbx secret set LITELLM_VIRTUAL_KEY sk-...
sbx secret set GITHUB_TOKEN ghp-...        # only if you want --open-prs

sbx create --name maistro-rsi --kit ./deploy/sbx/kit shell
```

First boot runs `/opt/maistro/sbx-setup.sh`: waits for the private dockerd,
loads the preseed tars, writes the LITELLM_*/SANDBOX_* env to
`/etc/sandbox-persistent.sh`, configures gh's git credential helper, and
creates `/tmp/maistro-workspace`.

## 4. Run an RSI cycle against maistro-engine

```bash
sbx exec -it maistro-rsi -- bash -lc '
  maistro-rsi run \
    --repo-url https://github.com/BlakeMatthews-dev/maistro-engine \
    --goal "Reduce duplication in packages/maistro-core/src/maistro/router/" \
    --test-command "uv sync --frozen --offline && uv run pytest packages/maistro-rsi -q" \
    --json
'
```

What happens, all inside the microVM: shallow clone → builders agent patches
the clone (via your gateway, using the virtual key) → diff staged + captured →
tests run in a nested `maistro-engine-tests` container on the private daemon
(offline, sanitized env) → evolve benchmarks score baseline vs. candidate with
real model calls → Elo battle → JSON summary. Add `--open-prs` to push and
open a PR when tests pass **and** quarantine clears. Exit code 0 = tests
passed.

Useful flags: `--model` (hard model override), `--models m1 m2` (quota-burn
pool; default = discover from the gateway), `--keep-workspace` (keep the clone
for debugging), `--max-turns N`.

## 5. Arbitrary codebases

**RSI:** point it at any https repo; supply that repo's own test image if its
test suite needs more than `maistro-engine-tests` carries:

```bash
sbx exec -it maistro-rsi -- bash -lc '
  SANDBOX_IMAGE=python:3.12-slim maistro-rsi run \
    --repo-url https://github.com/you/yourrepo \
    --goal "..." --test-command "pip install -e . && pytest -q"'
```

(Preseed extra images by adding `docker image save` lines to
`deploy/sbx/build.sh`, or `docker load` them via `sbx exec` — pulling from
inside requires temporarily allowing registry domains, which defeats the
egress posture.)

**builders (interactive):** mount any repo as the sandbox workspace and run
the TUI inside:

```bash
sbx create --name mycode --kit ./deploy/sbx/kit shell ~/code/yourrepo
sbx exec -it mycode -- bash -lc 'cd /workspace && maistro builders'
```

Use `--clone` on `sbx create` for an isolated copy (host dir stays read-only).

**evolve (standalone benchmark runner):**

```bash
sbx exec -it maistro-rsi -- bash -lc '
  python -m maistro_evolve.executable_terminal_runner --provider openai-compatible'
```

## Environment reference

Every alias is set to the same value by `sbx-setup.sh` (and re-normalized by
`maistro-rsi run` itself), because different subsystems read different names:

| Variable | Read by | Value |
|---|---|---|
| `LITELLM_BASE_URL` / `LITELLM_URL` / `LITELLM_PROXY_URL` | evolve / builders / builders | gateway base, **no `/v1`** |
| `LITELLM_MASTER_KEY` / `LITELLM_PROXY_KEY` / `LITELLM_API_KEY` / `LITELLM_VIRTUAL_KEY` | builders / builders / evolve / evolve | the virtual key |
| `SANDBOX_IMAGE` | nested test containers | `maistro-engine-tests:latest` |
| `SANDBOX_TIMEOUT` | nested container TTL (`sleep N`) | `3600` |
| `GITHUB_TOKEN` | `gh` (only `--open-prs`) | via `sbx secret` |

## Hardware verification checklist

These require a real machine with `sbx` installed (not verifiable in
CI/containers):

- [ ] `sbx kit validate ./deploy/sbx/kit` accepts the spec (kit schema is
      experimental upstream; adjust key names per `sbx kit --help` if not).
- [ ] The LiteLLM endpoint is reachable **through the sbx proxy** from inside
      a sandbox: `sbx exec maistro-rsi -- curl -s $LITELLM_BASE_URL/v1/models`.
      Non-443 `host:port` allowlist behavior is undocumented upstream — if
      blocked, front the gateway with TLS on 443.
- [ ] `sbx secret` values are visible to the kit install command (ordering),
      or move key setup to first `sbx exec`.
- [ ] First boot: preseed `docker load` completes before the first
      `maistro-rsi run` (watch `sbx exec ... docker images`).
- [ ] Offline `uv sync --frozen --offline` succeeds inside the nested test
      container against a fresh maistro-engine clone.
- [ ] `--open-prs`: https push + `gh pr create` succeed through the
      github.com/api.github.com allowlist entries.
- [ ] One full `maistro-rsi run` against maistro-engine ends with a JSON
      summary and (on a clean pass) a quarantine-cleared PR.
