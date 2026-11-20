---
inventory-delta:
  packages/maistro-rsi/tests: +0
  packages/maistro-bootstrap/tests: +0
---

# L80 round 22 — unstated-isolation fail-closed (ADR-093 decision 5) + both-daemon live re-proof

Branch `auto-80`, head `881fdad69d43d52fe5632c7925657a12f8afee93`, issue #80,
2026-09-27. Net test delta (+8, all in `packages/maistro-rsi/tests`) is
recorded once, in `auto-80-6b5f.md`; this note records +0 to keep its own
block truthful.

## The finding this round repairs

The prior verify round at this exact head returned NEEDS-REPAIR on two
findings: (1) the default autonomous RSI path executed model-generated work in
`LocalWorktreeSandbox` on the host — contrary to ADR-093 decision 6's floor
and decision 5's "no bare-subprocess tier"; (2) that verifier only had the
rootful daemon, so the rootless live escape assertions skipped.

## Repair: an unstated isolation now refuses at every entry

The tier guard (rounds 4-5) refused a *stated* Tier-3 backend but the
vocabulary still defaulted to `local`: `--isolation` defaulted to `"local"` in
both parsers, `LocalRsiConfig.isolation` defaulted to `"local"`, and
`make_builders_apply_patch(isolation="local")` — so a bare `run`/`evolve`
invocation reached host execution through nobody's decision. That is exactly
the bare-subprocess tier ADR-093 decision 5 forbids. ADR-082926-a6ab's
accepted carve-out covers an operator who *chose* `local` on their own
machine; it does not cover a default.

The repair keeps the two accepted ADRs each in their lane:

- `autonomous_isolation_refusal` gains an unstated branch (`""`/`None`):
  refuses, naming ADR-093 decision 5 and `--isolation local` as the way out.
  The tier-driven semantics are untouched (the `TestPolicyLinkage` pin still
  passes: a future `vm` wiring is neither cleared nor damned by a name it
  cannot map).
- `LocalRsiConfig.isolation` defaults to `""` (unstated refuses at `run()`);
  `make_builders_apply_patch` takes `isolation` as a required keyword, checks
  the guard, and additionally refuses any name it cannot *construct* (the
  apply closure's fallback branch is the host worktree — a typo like
  `isolation="locaal"` must degrade into a refusal, never into that branch).
- Both CLI parsers (`run`, `evolve`) default `--isolation` to unstated; the
  fail-closed refusal fires first, before the repo check.
- Explicit `local` proceeds everywhere (ADR-082926-a6ab); `container` keeps
  its decision-6 refusal; `LiveCodeFixer` defaults to unstated so a
  programmatic evolve cannot silently host; the `maistro-rsi` tournament CLI
  (`cli.py`) states `isolation="local"` explicitly at its call site — its
  contained mode remains open work, now visible instead of silent.
- SECURITY.md §8 records the both-sides posture.

## Tests (+8 net; see `auto-80-6b5f.md` for the recorded delta)

`test_autonomous_isolation_tier.py` 10 → 15: CLI fail-closed on unstated
`run`/`evolve`, explicit-local-still-proceeds, library unstated refusal, the
guard message test, and a `TestFactoryRefusal` class (unstated, unconstructible
name, container, explicit-local). 24 `LocalRsiConfig` sites, 4 override-dict
helpers, 4 factory calls and 4 CLI argv lists now state `local` explicitly.

## Validation battery (all commands run this round, this tree)

- `uv run pytest packages/maistro-rsi/tests -q` → **801 passed** (was 793).
- `uv run pytest packages/maistro-bootstrap/tests -q` (rootful daemon) →
  **247 passed, 17 skipped**; refusal test run solo on the same daemon →
  **1 passed**.
- **Rootless daemon** (`DOCKER_HOST=unix:///run/user/1000/docker.sock`):
  `test_container_sandbox.py -v` → **16 passed, 1 skipped** (the skip is the
  correctly-inverted rootful-refusal test) — live filesystem, network
  default-deny, non-root user, seed hygiene (`.env`/`.git`/secrets never
  seeded), credential default-deny, read-only rootfs + `/workspace`+`/tmp`
  writable scope, process/namespace/device/host-socket isolation, timeout kill
  incl. detached descendants, cleanup, 3 GiB memory containment, live uid_map
  probes; `test_container_sandbox_hardening.py` → **24 passed**. This closes
  prior finding (2) locally: both daemon branches are live-proven at this
  head.
- `uv run pytest packages/hive-conductor/backend/tests/test_rsi_execution_containment.py -q`
  → **58 passed** (the conductor's containment policy is unaffected; its
  service layer already requires an explicit `isolation="container"`).
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 2601 files
  formatted.
- `scripts/check-suite-inventory.py` → rsi drift +8 recorded via
  `auto-80-6b5f.md`; bootstrap suite ok (264); all suites ok after recording.
- `scripts/check-promotion-surface.py` → **promotion surface: ok**.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **1403 reviewed identities == 1403 findings**,
  exit 0 — no ledger amendment needed; the repair eliminated no identities and
  added none.
- `scripts/check-ac-state.py` → rc 0.

## Residual / handoff

- Remote CI green at/above this head remains the operational handoff item
  (pushing is prohibited for this lane); the designated conformance lane is
  configured (`ci.yml:464-570`), workflow-lint-clean at the pinned tools per
  round 21, and both of its daemon branches are locally proven above.
- The `maistro-rsi` tournament cycle (`cli.py`/`runner.py`) still edits and
  benchmark-validates in a host workspace; the choice is now explicit at the
  factory call site, but wiring a contained mode through `RsiCycleConfig` is
  separate work, as is `code_fixer.py`'s contained path beyond the factory
  gate.
