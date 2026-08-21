# VPS / host sizing

**What's the weakest box that can run maistro-engine?** There is no official
minimum. [ADR-081](../adr/ADR-081-deployment-backup-dr.md) is deliberately
**measure-first** — it sets *no hard numeric throughput targets*, and concurrency
caps are established empirically per deployment with backpressure via the
[ADR-071](../adr/ADR-071-task-planner-orchestration.md) reconciler. The numbers below are
**practical estimates** derived from the default stack, not a contract. Measure
your own workload before committing to a tier.

---

## What you are actually hosting

The default [`docker-compose.yml`](../../docker-compose.yml) brings up five
long-running services on one host:

| Service | Image | Rough idle RAM |
|---|---|---|
| `maistro-engine` | FastAPI / Python app | ~300–500 MB |
| `postgres` | `pgvector/pgvector:pg17` (hosts the `maistro`, `litellm`, and `langfuse` DBs) | ~400–700 MB |
| `litellm` | `ghcr.io/berriai/litellm` proxy | ~300–500 MB |
| `langfuse` | `langfuse/langfuse:2` (Next.js) | ~700 MB–1 GB ← heaviest |
| `open-webui` | chat UI | ~400–600 MB |

**Plus the part that dominates real load: per-task sandbox containers.** The
engine spawns isolated containers to run agent code.
[`DEPLOYMENT-STANCE.md`](../product/DEPLOYMENT-STANCE.md) requires a sandbox
worker for any official/production install — *"workerless execution is never
supported in production."* Each concurrent task needs its own memory headroom
**on top of** the baseline above.

---

## Tiers

### Bare minimum — kick the tires (single user, idle, trimmed stack)

**~2 vCPU / 4 GB RAM / 25 GB SSD.**

- Run the `full-headless` profile from `DEPLOYMENT-STANCE.md`: drop `langfuse`
  and `open-webui` from compose. That is where most of the RAM goes.
- You *can* technically boot `engine + postgres + litellm` on a 2 GB box, but
  the first build or sandbox task will OOM. **4 GB is the realistic floor.**

### Comfortable — full default stack

**4 vCPU / 8 GB RAM / 40–80 GB SSD**, covering engine + postgres + litellm +
langfuse + open-webui plus a few concurrent sandbox tasks.

Scale RAM and vCPU with expected task concurrency — the sandbox containers, not
the idle services, are what grow under load.

---

## The caveat that can change the answer: sandbox isolation tier

The isolation backend matters more than raw RAM. `DEPLOYMENT-STANCE.md` defines
two tiers:

- **VM-grade** (Kata Containers / Firecracker) — required for genuinely
  **untrusted** code. The installer preflight checks for **`/dev/kvm`**. Most
  budget VPS plans are themselves KVM guests and do **not** expose nested
  virtualization, so you cannot run VM-grade isolation on them. This pushes you
  toward bare metal / a dedicated host, or a VPS that explicitly offers nested
  virt.
- **Non-VM** (gVisor / rootless Podman) — no KVM needed, runs fine on an
  ordinary VPS, but is only sanctioned for **trusted / first-party** code.

| Scenario | Weakest viable host |
|---|---|
| Trusted / homelab code, gVisor or rootless sandbox | a normal **2 vCPU / 4 GB** headless VPS |
| Untrusted code with VM-grade isolation | needs **`/dev/kvm`** — usually bare metal or a nested-virt-capable host, not the cheapest VPS tier; RAM stops being the binding constraint |

> **Dev-only footgun:** the default compose still mounts the host Docker socket,
> which `DEPLOYMENT-STANCE.md` flags as **dev-only, never production**
> (CRIT-01). Production should use the separate sandbox worker, which adds a
> little overhead beyond the figures above.

---

## Related

- [ADR-081 — Deployment Topology, Backup, and Disaster Recovery](../adr/ADR-081-deployment-backup-dr.md) (measure-first capacity stance)
- [DEPLOYMENT-STANCE.md](../product/DEPLOYMENT-STANCE.md) (supported profiles, isolation tiers, preflight checks)
- [resolver-matrix.md](./resolver-matrix.md) (feature selections → compose profiles)
</content>
</invoke>
