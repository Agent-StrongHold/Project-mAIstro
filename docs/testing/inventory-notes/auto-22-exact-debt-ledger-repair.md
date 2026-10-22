---
inventory-delta:
  packages/maistro-core/tests: +0
---

# auto-22 (EPIC M4-B, #22) repair round — exact-debt-ledger (vulture per-identity ledger)

This round added **no tests**; the learnings suite is unchanged (the same
tests recorded by the #22 implementation round: gauntlet, lifecycle,
learning-lifecycle-store conformance, pg/sqlite learning stores). It repairs
the one gate this lane is assigned: `exact-debt-ledger`, which failed at head
`e29a0a47a51d` because the #22 commit shipped its M4-B feature surface without
banking the identities vulture now reports, and left one ledger row stale.

## What the gate actually reported at the starting head

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` → RC 1 with two failure
classes:

1. **5 NEW identities not in the ledger** — all in the M4-B code the #22
   commit itself added: `OutcomeEvidenceGauntlet`, `ChainedGauntlet`
   (gauntlet.py, #118), `effectiveness` (lifecycle.py, #119/#120),
   `LearningPromoter.capture_anti_patterns` (promoter.py, #121), and
   `LearningLifecycleStore` (protocols/memory.py, #117).
2. **1 recorded identity no longer found** —
   `store.py::unused method 'list_ineffective'`: the #22 promoter reads it
   through `IneffectiveLearningSource`, which marks the name used, so the
   recorded row went stale.

## Why whitelisting, not a ledger grant

`ratchet_provenance.load_authorizations` reads grants **from the base
revision**, by design (Codex, #534): "a new grant does not take effect in the
change that introduces it." The debt-bearing change is already the branch
head, so no grant added in this branch can authorize it — the only in-branch
dispositions are eliminate (delete genuinely dead code), wire, or whitelist
with a reviewed rationale. None of the five is dead: all five are the issue's
acceptance surface, exercised directly by
`packages/maistro-core/tests/memory/learnings/`, with production consumers
that are downstream-product configuration (a configured Gauntlet) or
external-scheduler calls (`capture_anti_patterns`), the same postures this
file already records for `CampaignSelector` and `PersistedStore`. The
whitelist block in `packages/maistro-core/src/_vulture_whitelist.py` carries
that rationale per identity.

## Ledger amendment (permitted and required in this CI-repair round)

Two rows pruned from `quality/vulture-baseline.json`, both because the
identity no longer produces a finding:

- `promoter.py::unused class 'LearningPromoter'` — the whitelist's
  `LearningPromoter.capture_anti_patterns` attribute reference marks the
  class name used.
- `store.py::unused method 'list_ineffective'` — genuinely used by the
  promoter since #22; the row was stale, not the code.

Together with the uncommitted repair work this branch inherited (19 rows
pruned for identities its develop-sync code already eliminated), the ratchet
now reads: **1390 reviewed identities → 1369 findings**, 0 unclassified,
0 never-allowlist — debt moved down, nothing unbanked.

## Salvage inconsistency corrected (one file)

The inherited uncommitted sync deleted `scripts/check-reachability.py` while
the tree's own `quality.yml` step and seven sibling checkers
(`check-ac-state-impl`, `check-model-egress`, `check-execution-lifecycles`,
`check-convergence-matrix`, `check-credential-authority`,
`check-reachability-provenance`, `check-wiring-reads`) import it by path;
`origin/develop` still ships it. The file was restored verbatim from the
starting head before committing; the full inherited diff is preserved at the
job directory (`incoming-22.patch`) with this one reversion noted.

## Executed evidence (this round, this tree)

- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **RC 0** (1390 → 1369, 0 unbanked, 0 stale).
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests/memory/learnings -q` → 180 passed.

## Known residual, measured this round (pre-existing, not this lane's gate)

The inherited uncommitted develop-sync state fails three further ratchets,
each with the same structural wall as a vulture grant — the trusted-base
authorization cannot be self-landed in-branch (Codex, #534) — recorded here
as actual evidence for the round that owns the Quality gate:

- **reachability ratchet** (`check-reachability.py` → RC 1): exactly one
  newly-unreachable module, `maistro.memory.learnings.gauntlet` — #22's
  library-only Gauntlet module; nothing that runs imports the promoter stack
  yet, and the candidate `quality/reachability-baseline.json` does not bank
  it. Eliminating it means wiring `LearningPromoter` into a process entry
  point — a #118/#450 product decision, not a repair-lane one.
- **contract-markers ratchet** (RC 1):
  `declared-kind-unproven::docs/adr/ADR-100126-9a4b-validated-collective-learning.md
  [behavioral]` — the #22 ADR's declared behavioral claims are unproven and
  unbanked. Corresponds to the failing "Validate ADR/spec front-matter" CI
  job.
- **enumerations ratchet** (RC 1):
  `sensitive_paths::pattern:…rsi_container_dispatch.py` (+ its test file) —
  salvage-synced files not classified in the candidate enumeration ledger.
- Consequently `check-ratchet-provenance.py` reports its inventory
  incomplete on exactly those three sub-gates; the vulture ratchet itself is
  not among them and is proven green above.
