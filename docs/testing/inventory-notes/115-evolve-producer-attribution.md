---
inventory-delta:
  packages/maistro-evolve/tests: +40
---

# Evolve producer attribution — candidate lineage and operator credit (#115, M4-A8)

Adds `maistro_evolve.attribution` and wires it through the existing search
loop: every produced candidate (mutation children, crossover children,
reflect challengers, hyper-mutator challengers) now carries a frozen
`CandidateOrigin` recording the producing operator's registered identity and
version, its parents/upstream, the parent's stored scores as the credit
baseline, the producing chain, and the evaluation context.

The new tests cover, per acceptance criterion:

- lineage identity: each operator stamps its own `ProducerIdentity`
  (kind/name/version from `PRODUCER_VERSIONS`); unregistered producers fail
  closed; origins survive the sqlite population round-trip; stamping is
  once-only (`stamp_origin` refuses rewrites).
- credit without history rewrite: `ProducerLedger.credit` classifies
  improvement/regression/neutral against the frozen baseline, appends
  strictly-sequenced immutable events, and never mutates the candidate's own
  origin/lineage; cycle evaluation credits producers end-to-end (and records
  nothing when `producer_attribution=False`); unattributable seed genomes are
  simply outside the ledger.
- favoring with diversity: `operator_weights` ranks productive operators
  higher, floors every operator's share (`exploration_floor`) so a dominant
  operator cannot starve the rest, and `select_operator` keeps all operators
  reachable; cycle breeding draws ledger-weighted operator subsets only when
  `favor_productive_operators=True` (default stays the legacy
  apply-every-operator path).
- negative credit retention: regression counters never decay;
  `credit_rejected_proposal` retains verified-but-received-rejection credit;
  stub (SPEC-202 noise) evaluations count as failures without diluting
  success rates; repeated regressors are demoted but never zeroed.
- audit + scoping: statistics are bucketed per evaluation context
  (fidelity + benchmark set + scope, canonicalized key); `attribution_report`
  dumps the append-only log (optionally scoped to one context).

Develop-merge update (b4b9e187e): `mutate_eval_weights` was removed upstream
(#853, objective is population-owned), so the operator disappears from
`MUTATION_OPERATOR_NAMES`, `PRODUCER_VERSIONS`, and the origin-stamping
parametrization. One test was added pinning the merged crediting contract:
#854 reconfirmation shares the attribution path — each fresh verified sample
of a candidate appends another credit event for its producer (attempts
accumulate; candidate history is never rewritten), while
`reconfirm_per_cycle=0` still yields exactly one first-eval credit.
