---
inventory-delta:
  packages/maistro-rsi/tests: +46
---
# 109-evaluator-oracle-immunity

Issue #109: protect evaluator/scenario/AC/ratchet artifacts from RSI mutation
— a candidate scored by `LocalRsiLoop` may satisfy the oracle but may not edit
it in the diff that is judged against it.

The forty-five new nodes in `packages/maistro-rsi/tests/test_evaluator_immunity.py`
plus one in `test_sensitive_paths.py` cover, in order of the attack they close:

- the two pattern tiers themselves: `EVALUATOR_ORACLE_PATTERNS` must cover the
  scorer, its pinning tests, the scenario corpora, the vendored graders, the
  ratchet baselines and the AC trees, and must leave the application surface
  (the code candidates are supposed to improve) alone; `docs/specs/` also
  escalates on the sensitive (export) tier; the generated-artifact patterns
  (`__pycache__/`, `*.egg-info/`, import-time hooks) catch the
  oracle-execution hijacks no listed path reveals;
- `oracle_mutations` against real git worktrees: the bypass spells are each a
  focused node — direct scorer edit, `git mv` rename/move (both endpoints
  flagged), the `status --porcelain` `old -> new` spelling, symlink swap of a
  pinning test, committed poison bytecode and `sitecustomize.py` anywhere in
  the tree, and a fail-closed node proving an unusable baseline is a
  violation, never silence;
- the AC-tree semantics: rewriting an inherited AC checkbox is a violation,
  while drafting a NEW spec contract (the designed `spec_proposed`
  contribution) stays allowed;
- scorecard enforcement: a mutated oracle withholds ALL evidence before the
  test command runs (the spy sees zero oracle executions), pins the trusted
  base digest into `Scorecard.evaluator_digest`, and the governance override
  scores but records mutations + digest — never silent; a separate node pins
  the property that the digest actually identifies the evaluator version;
- follow-up rounds hardened the fixture set without changing the design: the
  ignored-worktree layer gained a paired node proving *benign* ignored output
  (a scratch log matching no generated pattern) does not veto a clean
  candidate, the clean-candidate promotion node now pins the trace-note and
  export-manifest provenance (digest present, `evaluator_authorized` false),
  and `test_sensitive_paths.py` gains the bare-directory-name matcher node —
  git reports a symlink named like a protected directory as a path with no
  trailing slash, which startswith/containment alone let slip past both tiers;
- the adversarial self-scoring fixture end to end: one candidate diff that
  weakens the scorer, guts its pinning test, flips an inherited AC, edits a
  ratchet baseline and plants an import-time hook cannot reach
  `accepted=True` on either acceptance path (fitness or bare test command),
  and the baseline ref demonstrably never moves — so the #302 promotion
  prerequisites (which consume acceptance) cannot be met from oracle
  self-mutation. A counterfactual node runs the same fixture with the
  integrity check disabled and watches it promote, proving the vetoes are
  load-bearing rather than vacuous; the authorized-override run promotes and
  carries the evidence through the git-notes record AND the export manifest;
  a merge-dir node proves the combination is re-checked without precomputed
  evidence.

No existing suite lost nodes: the two pre-scoring veto paths and the new
scorecard gate are additive, and every prior fixture candidate edits only
application-surface paths, so the guard is invisible to them (the full
`packages/maistro-rsi/tests` + `packages/maistro-evolve/tests` run passes
at 1868 passed, 6 skipped, re-verified after the follow-up rounds and the
develop sync).
