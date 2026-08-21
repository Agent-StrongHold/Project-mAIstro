---
id: SPEC-062826-1924
title: "Test hardening: adversarial probing, state/IO matrices, and exploratory testing — turning up coverage of trust boundaries and state machines"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-28
substrate:
  - maistro-engine#ADR-032
implements: []
related:
  - maistro-engine#SPEC-205
  - maistro-engine#SPEC-253
  - maistro-engine#SPEC-062826-8982
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/credentials/test_credential_store.py
  - formal/models/test_auth_registry.py
  - packages/maistro-core/tests/auth/test_provider.py
  - packages/maistro-core/tests/tasks/test_status.py
  - packages/maistro-core/tests/test_circuit_breaker.py
  - packages/maistro-core/tests/capabilities/test_self_repair_governor.py
  - packages/maistro-core/tests/a2a/test_delegate.py
  - packages/maistro-core/tests/tools/test_env_sanitize.py
  - packages/maistro-core/tests/tools/test_workspace.py
  - packages/maistro-core/tests/capabilities/test_discovery.py
  - packages/maistro-core/tests/credentials/test_pool.py
  - packages/hive-conductor/backend/tests/test_auth_middleware.py
  - packages/maistro-core/tests/skills/test_canary.py
  - packages/maistro-core/tests/tasks/test_checkpoint_replay.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Implemented
    date: 2026-06-28
---

# SPEC-062826-1924: Test hardening — adversarial, state/IO matrix, and exploratory testing

## Problem

Three testing patterns existed in the suite at a "basic" level — each with exactly one
gold-standard example, but no systematic coverage:

1. **Adversarial testing.** Only `packages/hive-conductor/eval/adversarial/guardrail_probes.py`
   and a handful of `formal/models/test_warden_*.py`/`test_sentinel_*.py`/`test_pii_filter.py`
   Hypothesis fuzz tests exercised fixed hostile-input sets. Most other trust-boundary code —
   credential storage, the B2B auth registry/provider, the auth middleware's path-matching, the
   sandbox path/env validators, capability discovery — had only example-based tests, or none.
2. **State/IO matrix testing.** Only `packages/maistro-core/tests/tools/test_approval_gate.py`
   (`maistro-engine#SPEC-253`) fully walked a (state × input) grid. Other explicit state
   machines — task status, A2A delegation status, the circuit breaker, the self-repair governor —
   had example-path tests covering the happy transitions, not the full transition table.
3. **Exploratory testing.** Happened informally via ad-hoc debugging and the `run-formal`/
   `verify-evolve` skills, with no log format and no path from "noticed something while poking"
   into a tracked backlog item or regression test.

Two concrete bugs (`ServiceKeyRegistry` stale-key mapping, `AuthMiddleware` sibling-prefix
confusion — both documented below and in `maistro-engine#SPEC-062826-8982`) were found through
unscripted adversarial probing while building the *automated* suites described here, which is the
clearest evidence that all three patterns were underused: the automated tests that exist today
would not have caught either bug on their own.

## Design

### 1. Adversarial testing — trust-boundary hostile-input coverage

Extended or added fixed/fuzzed hostile-input suites at every trust boundary that previously had
none, modeled on `guardrail_probes.py`'s probe-list style and the existing `formal/models/`
Hypothesis convention:

- `packages/maistro-core/tests/credentials/test_credential_store.py` — Hypothesis-fuzzed
  `UserCredentialStore._load/.set_secret/.use_secret` (`credentials/store.py`) with corrupted
  base64 Fernet tokens, valid-Fernet-but-non-dict-JSON payloads, and wrong-key decrypts.
- `formal/models/test_auth_registry.py` — fuzzed `ServiceKeyRegistry.load_yaml/load_env`
  (`auth/registry.py`) with malformed YAML and colliding env-derived key hashes, asserting it
  degrades (log + skip) rather than raising. This pass surfaced the stale-key-mapping and
  unguarded-YAML-parsing bugs fixed in the same change (see `BACKLOG.md#engine-110`).
- `packages/maistro-core/tests/auth/test_provider.py` (new) — guardrail-probe-style fixed
  adversarial header set against `ServiceKeyAuthProvider._extract_key/.authenticate`: header-case
  variants, malformed Bearer tokens, NUL-byte injection, oversized values.
- `packages/maistro-core/tests/tools/test_env_sanitize.py` — Hypothesis-fuzzed secret-shaped
  strings near `_SECRET_PATTERN`'s boundary, plus a ReDoS timing-bound regression test.
- `packages/maistro-core/tests/tools/test_workspace.py` — fixed traversal payloads (Unicode
  normalization tricks, symlink escapes, null-byte truncation) against
  `validate_workspace_path()`.
- `packages/maistro-core/tests/capabilities/test_discovery.py` (new) — fake `EntryPoint`s that
  raise every failure shape against `discover_into()`, confirming one bad provider never blocks
  registration of the rest.
- `packages/maistro-core/tests/credentials/test_pool.py` — `RuleBasedStateMachine` (mirrors
  `formal/models/test_strike_escalation.py`) over concurrent `select/record_failure/record_success`.
- `packages/hive-conductor/backend/tests/test_auth_middleware.py` (new) — path-matching bypass
  grid against `AuthMiddleware.dispatch`. This suite surfaced the sibling-prefix-confusion and
  substring permission-carve-out bugs fixed in the same change (see `BACKLOG.md#engine-111`).

### 2. State/IO matrix testing — full transition-table coverage

- `packages/maistro-core/tests/tasks/test_status.py` (new — zero coverage existed before) — full
  8×8 parametrize grid over `TaskStatus × TaskStatus` against `can_transition()`
  (`tasks/status.py`), independently re-deriving the expected edge set rather than re-importing
  `TRANSITIONS`, so the test can't trivially pass. Covers all three terminal states' empty
  transition sets and explicit self-transition checks.
- `packages/maistro-core/tests/test_circuit_breaker.py` — 3-state × 4-event grid against
  `CircuitBreaker` (`agents/circuit_breaker.py`), with `monkeypatch` on `time.monotonic` for the
  HALF_OPEN-on-elapsed-time boundary (the breaker calls `time.monotonic()` directly, not through
  an injectable clock).
- `packages/maistro-core/tests/capabilities/test_self_repair_governor.py` — boundary-focused
  cross-product over `(in_flight, flap_count, attempts_in_window, cooldown_elapsed)` at
  representative values (0, threshold−1, threshold, threshold+1), not full Cartesian explosion.
- `packages/maistro-core/src/maistro/a2a/delegate.py` (source change) — `update_task_status()`
  had no transition guard at all; any of its 6 `TaskStatus` values could follow any other
  (`COMPLETED → QUEUED` silently succeeded). Added a `_TRANSITIONS` table mirroring
  `tasks/status.py`'s pattern (A2A's `TaskStatus` is a separate, narrower enum — unifying the two
  is a bigger follow-up, out of scope here) and made `update_task_status` reject invalid edges.
  `packages/maistro-core/tests/a2a/test_delegate.py` was confirmed to have no caller relying on a
  previously-invalid transition before the guard landed, then extended with the matrix test
  against it.
- Boundary extensions to `packages/maistro-core/tests/skills/test_canary.py` and
  `packages/maistro-core/tests/tasks/test_checkpoint_replay.py` (malformed/mismatched-sequence
  cases added to the existing Hypothesis property test, not a new matrix).

### 3. Exploratory testing

Specified and shipped separately as `maistro-engine#SPEC-062826-8982` — a session-log template
under `docs/exploratory-sessions/`, a `BACKLOG.md` escalation path, and `run-formal`/
`verify-evolve` skill-doc integration. Kept as its own spec because its acceptance criteria are
doc/process checks rather than `path::func` test anchors; folding it in here would have muddied
this spec's `tests:` front-matter field. See that spec for full design and proof of the loop
closing (two historical backfills, one dogfooded session, both escalated/regression-locked).

## Non-goals

- Unifying `tasks/status.py`'s `TaskStatus` and `a2a/delegate.py`'s `TaskStatus` into one enum —
  the two model different lifecycles (task execution vs. cross-agent delegation) and merging them
  is a larger refactor than this hardening pass.
- `maistro_canvas/auth.py` — still a no-op stub; out of scope here, tracked as a follow-up only.
- Replacing or gating CI on any of this — these are test additions and one narrow source guard
  (the A2A transition table), not new CI jobs or coverage-gate changes (that's `SPEC-205`'s scope).

## Acceptance Criteria

- [x] Credential store, auth registry, and auth provider each have adversarial hostile-input
      coverage where none (or only example-based coverage) existed before
- [x] Sandbox env-sanitize and workspace-path validators have adversarial coverage (Hypothesis
      fuzz + fixed traversal-payload grid respectively)
- [x] Capability discovery has adversarial coverage confirming one failing provider never blocks
      or partially registers the rest
- [x] `AuthMiddleware.dispatch` has a path-matching bypass grid (zero tests existed before)
- [x] `tasks/status.py::can_transition` has a full, independently-derived 8×8 transition matrix
      test (zero tests existed before)
- [x] `CircuitBreaker` and the self-repair governor each have boundary-focused state×input matrix
      coverage
- [x] `a2a/delegate.py::update_task_status` rejects invalid transitions (previously accepted any
      transition) and has matrix coverage against the new guard
- [x] Two real bugs found via adversarial/exploratory probing while building this suite
      (`ServiceKeyRegistry` stale-key mapping, `AuthMiddleware` sibling-prefix bypass) are fixed
      in the same change and regression-locked
- [x] Exploratory testing program shipped per `maistro-engine#SPEC-062826-8982`
