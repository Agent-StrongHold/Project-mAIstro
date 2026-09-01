# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions are **lockstep across the monorepo**: every published package carries
the same version as the root `VERSION` file.

## [Unreleased]

### Changed

- **HALF_OPEN circuit-breaker success is now caller-bound.** `record_success()`
  closes a HALF_OPEN circuit only when called by the thread or asyncio task
  whose `allow_request()` call acquired the current exclusive probe lease;
  successes from other callers are ignored. A probe owner can call
  `release_probe()` to let another caller claim the probe.

## [1.0.0] - TBD

First tagged release. Prior to this, the repository had no tags, no release
workflow, and no changelog; `develop` was the only integration point.

### Headline

- **Evolve + RSI ship as first-class v1 features**, not experiments — a genome
  tournament optimizer (`maistro-evolve`) and a recursive self-improvement loop
  (`maistro-rsi`) that proposes, sandboxes, and scores changes to this very
  repository.

  **Read this caveat before trusting a score.** The benchmark scorers are
  **proxy-tier** and are now named accordingly — `proxy_ifeval`, `proxy_bfcl`,
  `proxy_swebench`, `proxy_tau_bench`, `proxy_gaia`, `proxy_ragas`,
  `proxy_terminalbench`, `proxy_swebench_pro`. **None of them runs the official
  published benchmark harness against the official dataset**; all score real
  model output at a small, handcrafted scale. Fidelity is *not* uniform even
  within that tier: `proxy_swebench`/`proxy_terminalbench` execute candidate
  code in a real sandbox and assert a real outcome, `proxy_ifeval` performs
  genuine per-instruction rule checks, while `proxy_bfcl`, `proxy_gaia`, and
  `proxy_tau_bench` each carry a text-mention or fuzzy-substring fallback that
  materially weakens them, and `proxy_ragas` is primarily keyword overlap.
  `proxy_osworld` is defined but not runnable. Per-benchmark detail —
  including the exact degenerate cases — is in
  `packages/maistro-evolve/CLAUDE.md`. Real official-harness adapters are
  v1.1 (SPEC-202).

### Added

- **`maistro-core`** — the shared runtime, published to PyPI: memory
  (learnings, episodic, scopes, outcomes), security (Warden threat detection,
  Sentinel policy, PII filtering), classifier, router, agents, builders, A2A
  delegation, skills, graph execution (ADR-062), ontology (ADR-036),
  resilience (ADR-038), quota, sessions, and the DI container.
- **`maistro-canvas`** — the standalone canvas ability: engine, PIL-based
  compositor, PostgreSQL store, REST routes, and protocol interfaces.
- **`maistro-server`** — a thin FastAPI wrapper over the core library.
- **hive-conductor** — the Agent Conductor application (FastAPI backend +
  React SPA). Not published to PyPI; shipped as a container image.
- **`maistro-bootstrap`** — installer and planner CLI.
- `docs/testing/SUITE-INVENTORY.md` — per-suite collected node-ID counts and
  the exact commands to regenerate them.
- `KNOWN-GAPS.md` — the curated register of shipped-but-limited behavior.

### Fixed

- **Unauthenticated arbitrary file read in the Conductor.** The SPA fallback
  route joined an attacker-controlled path onto the static root without
  containment. Because `pathlib` discards the left operand when the right one
  is absolute, `STATIC_DIR / "/etc/passwd"` resolved to `/etc/passwd` — no
  `..` needed — and the route is not behind `AuthMiddleware`, which
  authenticates only `/v1/` paths. Any file readable by the server process was
  retrievable without credentials, including the credential master key, the
  encrypted credential store, and the session database. Now resolved and
  containment-checked against the static root.

  **Operators upgrading from a pre-1.0.0 checkout that was network-reachable
  should treat the credential master key, stored integration credentials, and
  all active sessions as disclosed, and rotate and purge accordingly.** The fix
  prevents further reads; it cannot undo reads that already happened.
- **The Conductor no longer reports fake success when no LLM is configured.**
  The graph runner returned a normal-looking `{"response": "stub: no LLM
  configured", "done": true}` whenever `LITELLM_*` was unset, so a
  misconfigured deployment produced results indistinguishable from real ones.
  It now refuses outright. Set `ALLOW_STUB_LLM=true` to opt in to stub
  responses; those are labelled `"stub": true` in the payload so nothing
  downstream can mistake one for a real result.

  **This can look like a regression.** The graph runner reads `os.environ` and
  never picks up `LITELLM_API_BASE` from `backend/.env`, so a `.env`-only
  deployment was already silently receiving stubs and will now fail loudly
  instead. docker-compose passes the variable as a real env var and is
  unaffected.
- Canvas authentication no longer returns an admin user regardless of the
  supplied API key.
- Design PNG rendering returns a clean `501` rather than surfacing an
  unhandled `NotImplementedError`.
- Two canvas frontend runtime defects an absent lint gate had been hiding: an
  invalid duplicate ESM export that made a whole module unparseable by the
  linter, and a `ReferenceError` in a normalization fallback path.

### Changed

- Benchmark identifiers renamed to the `proxy_*` form described above. **This
  is a breaking change for any stored genome, fitness configuration, or
  tournament state keyed by the old bare names** (`ifeval`, `swebench`, …).
- Dependencies now carry upper bounds in every package.
- hive-conductor gained a `pyproject.toml` and joined the `uv` workspace.
  `backend/requirements.txt` **remains the install path** used by the
  Dockerfile and CI — change a dependency in both.

### Security

- Warden, Sentinel, and the strike ladder are wired through the DI container.
- Constant-time comparison for privilege and admin-key checks.
- CI runs bandit, semgrep, gitleaks, pip-audit, and container scanning.

### API compatibility

**The stable HTTP surface in 1.0.0 is the `/v1` route mount.** Clients should
address `/v1/...` paths directly.

[ADR-076](docs/adr/ADR-076-http-api-versioning.md) specifies version selection
by **content negotiation** (`Accept: application/vnd.maistro.vN+json`). **That
scheme is not implemented.** No server in this release performs it; the only
negotiation code anywhere in the tree is a narrow, canvas-specific
`/v2/canvas` media-type check unrelated to the general scheme. Do not write
clients against it. Implementation is deferred to v1.1.

The API version axis is independent of the package version: a `1.x` package
release does not imply a `/v2` HTTP surface.

### Supported deployment profiles

See [`docs/product/DEPLOYMENT-STANCE.md`](docs/product/DEPLOYMENT-STANCE.md)
for the supported-profile matrix. Configurations outside it are not covered by
the v1 support statement.

### Known limitations

Verbatim from [`KNOWN-GAPS.md`](KNOWN-GAPS.md), which is the maintained
register:

> v1.0.0 ships with an in-memory task queue, so a restart loses queued and
> active tasks. Canvas jobs require an external runner; Canvas publish and
> some export formats are not implemented. Conductor can run in degraded mode
> when optional services are unavailable. Canvas Studio has not completed its
> `/v2/canvas` cutover, and API-wide HTTP content negotiation from ADR-076 is
> deferred to v1.1.

[Unreleased]: https://github.com/Agent-StrongHold/Project-mAIstro/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Agent-StrongHold/Project-mAIstro/releases/tag/v1.0.0
