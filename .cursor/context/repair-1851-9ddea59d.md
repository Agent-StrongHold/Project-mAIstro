# Repair #1851 @ 7c2391cf3 (branch auto-1851) — 2026-10-20, CI-repair round

Re-derived every load-bearing check at the assigned head; no earlier claim assumed.
Worktree clean at start (7c2391cf3); origin/develop == fad17a87c == assigned base.

- Focused battery: `uv sync --locked --extra dev` ok; `ruff check .` All checks passed;
  `ruff format --check .` 3362 files; focused pytest `test_root_admission_identity.py` 79 passed;
  `check-suite-inventory.py` ok (21 suites, 32385 nodes, 0 dupes).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  with `RATCHET_BASE_REV=origin/develop`: rc=1. Banking half GREEN (scan 1326 == ledger 1326,
  no "must also be banked"/"must be pruned"). Authorization half RED on exactly the 5
  retained `AdmissionAssessment` identities at `admission_identity.py:515-520`
  (MISMATCH, REPLAYED, TAKEOVER, REPLACE_EXPIRED, LEGACY_UNRESOLVED; PENDING unflagged
  by name collision). Trusted base (fad17a87c) has 0 grants for them; two-merge wall.
- `check-reachability.py`: rc=1, exactly 1 NEWLY UNREACHABLE `maistro.runs.admission_identity`
  (intentionally unwired leaf per issue scope).
- `check-reachability-dispositions.py`: rc=0. `check-promotion-surface.py`: rc=0.
  `check-ratchet-provenance.py`: rc=1 solely via reachability provenance.

No code edit: the 5 identities are the issue's fixed `AdmissionAssessment` contract
(retained by design until #1845 wiring consumes them); no genuinely dead code exists
to delete, and no in-scope fix eliminates them without violating the issue's
prohibitions (no fake callers, no keep-alive imports, no suppressions, no allowlist/
baseline additions, no grants, no rename). The reachability blocker is the issue-
mandated unwired leaf. Both require the #1845 integration head + owner-landed develop
grants, outside this leaf.

Verdict: NEEDS-DEEP-REVIEW (leaf implementation/tests complete and correct; structural
gates remain owner-held blockers, not repairable here).
