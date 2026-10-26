---
inventory-delta:
  packages/maistro-core/tests: +10
  packages/maistro-turing/backend/tests: +12
---
# PR 1622 — one canonical Turing chat retention window

Turing's per-Workspace admitters share one ordered process budget and sweep
lock. Each entry retains its admitting Workspace's validation and liveness
checks. The existing limit, dispatch-pending/CREATED/QUEUED/live-Attempt
shields, oldest-first ordering and store integrity refusals remain canonical.
The dispatch seam sweeps again when each turn settles, including compensated
admission and cancellation exits.

Core gains eight parameterized cases: refusing a shared budget across different
stores or limits, and rechecking Workspace and chat provenance before deleting
a previously tracked Run, plus preserving the already-created identity without
an extra fallible/cancellable read before returning admission, and proving a
forged Run snapshot cannot authorize foreign-Workspace or task deletion. Turing gains the final-burst regression plus eleven
composition cases: five users sharing two slots, seven liveness states across
Workspaces, and foreign-Workspace/task/missing-Run tracking refusals. The
existing final-burst test now uses three separate users and admits no fourth
turn. The missing-entry test registers a real Run before simulating external
deletion. No tests were removed or skipped by this change.

Fail-first evidence: restoring the reviewed PR's independent per-Workspace
window wiring and summed `retained` projection makes the five-user and
three-user final-burst tests fail (five and three retained against two).
Normal shared composition passes these same assertions. All test stores are
isolated in-memory fixtures; no live user data is accessed or deleted.

This change does not close the broader retention/reference-integrity work in
#1175. In particular, `InMemoryRunStore.delete_run` does not reclaim Graph
continuations, unlike the separate purge API. The existing shared continuation
store and all current security/cancellation paths are preserved; this PR does
not add purge authority or a new retention policy. #131 is historical, already
closed independently.

## Package-separated coverage correction

Two direct core contract tests cover the successful shared-window composition
and externally admitted Run-ID tracking, including repeated tracking and a
missing-ID refusal that preserves the existing window. CI measures core and
Turing in separate coverage producers; Turing's composition proof alone cannot
count as coverage of core. These tests complement that product-path evidence
without changing production code or the coverage floor.

## Revalidation at the develop-merge head (2026-10-26)

The branch was merged with develop (`78133c093`) into `ce2a6d1dd`; the
conflict-free result keeps this PR's seven surfaces as its only delta against
develop, and `quality/` is byte-identical to develop (no ledger rows moved).
All gates were re-run at that head, no production change was needed:

- Behavioral: `uv run --frozen pytest
  packages/maistro-turing/backend/tests/test_chat.py
  packages/maistro-core/tests/runs/test_chat_admission.py -q --tb=line` —
  72 passed (29 Turing chat as above; core grew by develop's +10, the delta
  recorded in this note). Full `packages/maistro-turing/backend/tests` 137
  passed under the coverage producer; `packages/maistro-turing/tests` 225
  passed; `packages/maistro-core/tests/runs` 1505 passed / 368 skipped (the
  skips are the PostgreSQL legs).
- Ratchet gates, CI-exact invocations: vulture `packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` 1253 = 1253; radon
  127 = 127; reachability, promotion surface and direct-effect inventory all
  pass; suite inventory matches the recorded baseline plus this note's
  deltas (core 18037, Turing backend 137).
- Diff coverage reproduced package-separated (`--source` core over
  `tests/runs`, `--source` Turing backend over `backend/tests`, branch arcs):
  `check-diff-coverage.py --base 78133c093` — both measured files at or above
  90% lines / 80% branch arcs.
- SAST at the pinned CI versions: gitleaks 8.30.1 `no leaks found` over both
  `78133c093..ce2a6d1dd` and the pending push range `e7fd99e74096..ce2a6d1dd`
  (the historical fingerprints that failed earlier push scans at `8f05e0e8`
  are not in either range); semgrep 364 rules / 2258 files / 0 findings;
  bandit 0 Medium+ findings. Ruff check and format clean; mypy clean over the
  944-file package set.
