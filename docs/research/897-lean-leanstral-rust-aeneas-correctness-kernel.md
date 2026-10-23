# M8-A research note — Lean/Leanstral + Rust/Aeneas feasibility for a tiny MAIstro correctness kernel

Epic: #880. Leaf: #897. Initiative: #879.

## Research question

Can Lean — assisted by an LLM autoformalization accelerator ("Leanstral") on the
semantic-model path, or reached mechanically through Rust + Charon/Aeneas on the
translation path — provide materially stronger assurance for a very small
deterministic correctness kernel, and is the model/implementation fidelity
credible enough to justify the added language and tooling complexity?

## Canonical seam

The execution-state transition legality kernel — the issue's first candidate
kernel shape and the smallest deterministic decision surface on the canonical
spine:

- `packages/maistro-core/src/maistro/runs/lifecycle.py` — `RUN_TRANSITIONS`,
  `ATTEMPT_TRANSITIONS`, `transition_path`, plus the pure predicates around
  them (`check_completion_is_earned`, `lease_is_expired`,
  `refuse_completion_under_terminal_run`, `latest_node_runs`);
- `packages/maistro-core/src/maistro/runs/model.py` — the `RunStatus` /
  `AttemptStatus` enums and `TERMINAL_RUN_STATUSES` /
  `TERMINAL_ATTEMPT_STATUSES`.

Governed by ADR-081226-a66b (Run/NodeRun/Attempt lifecycle), ADR-082426-19ed
(a Run cannot claim success over a node that failed), ADR-082426-a47f, and
enforced structurally by `scripts/check-execution-lifecycles.py` (one lifecycle
vocabulary, not two).

The other four candidate kernel shapes (authorization decisions, Goal
ownership/delegation transitions, Graph legality invariants, effect/idempotency
rules) were deliberately not taken: each either already has a dedicated
in-tree model (Invocation effect idempotency is formal/ I31, evidenced under
#882) or drags in the authorization/event authorities this research must not
touch.

## What actually ran (and what did not — recorded, never simulated)

| Step | Status |
|---|---|
| Mechanical extraction of the kernel tables from the production source (AST, text-read) | **ran** — every CI run, in `packages/maistro-rsi/tests/test_m8a16_lean_rust_kernel_research.py` |
| Three-way equivalence: production table ↔ embedded Lean kernel ↔ embedded Rust kernel | **ran** — row-by-row, universes and terminal sets, every CI run; mutation-verified (a one-token Lean row edit fails as `lean run row drift at created`) |
| Python duals of the Lean theorems (terminal absorption, no self-loops, terminal reachability, path iff reachable, legal + shortest + deterministic) | **ran** — every CI run |
| Measured translatability of `lifecycle.py` (which functions sit on mechanically crossable boundaries) | **ran** — classification enforced against the AST |
| Lean proof checking (`elan` / Lean 4 on the embedded `LEAN_KERNEL`) | **did not run** — no Lean toolchain in this repo's deterministic CI; the artifact is a hand-checkable proof sketch, labeled as such in its header |
| Rust build + `cargo test` on the embedded `RUST_KERNEL` | **did not run** — no cargo in CI |
| Charon/Aeneas Rust→Lean translation | **did not run** — evaluated analytically against the measured module surface |
| Leanstral free API for autoformalization assistance | **did not run** — no network in deterministic CI, and a free-tier API must not become load-bearing; assessed qualitatively only |

Per M8 guardrail 3 the absences are the record: at this head nothing here is
evidence of assurance. It is evidence about the *feasibility surface*, which is
what the leaf asked to measure, and each absence has a named re-run step.

## The prototype (bounded, real code)

One test-suite-only module,
`packages/maistro-rsi/tests/test_m8a16_lean_rust_kernel_research.py`
(27 checks, imports nothing from `maistro`, reads production as text and never
writes it), carrying:

1. **The extraction** — production tables become model data mechanically. This
   is the answer to "can the semantic-model path keep its fidelity": for the
   chosen kernel the answer is *the model is not transcribed at all* — it is
   derived, so the transcription-error class is eliminated rather than
   measured for the tables themselves.
2. **`LEAN_KERNEL`** — a self-contained Lean 4 artifact: both enums, both
   tables, terminal sets, `stepLegal`, a `Reaches` inductive, a `LegalPath`
   inductive, and five theorems (`terminal_absorbing`,
   `attempt_terminal_absorbing`, `no_self_loops`,
   `nonterminal_reaches_cancelled`, `legal_path_ends_reaches`), each naming
   its machine-checked Python dual. Header status: NOT MACHINE-CHECKED IN THIS
   REPOSITORY.
3. **`RUST_KERNEL`** — the same kernel as safe sequential Rust (enums, static
   tables, BFS `transition_path`, a fixpoint reachability oracle, and its own
   `#[cfg(test)]` module), the candidate input for Charon/Aeneas. Header
   status: not built here.
4. **The measured equivalence and translatability records** — frozen dataclasses:
   9 Run rows + 7 Attempt rows equated three ways; 20 `lifecycle.py` functions
   classified 10 pure-decision / 10 boundary-bound (pydantic
   `model_validate`/`model_dump`/`model_copy`, wall-clock `_now`, `Any`-typed
   JSON evidence), with the classification enforced against the AST so the
   module's evolution fails the suite loudly instead of rotting the
   classification silently.

## Evidence questions answered

**What percentage of relevant logic can be mechanically translated?**
Two answers, both measured rather than estimated. For the *chosen kernel* —
the tables, step legality, and the path search — **100%**: everything relevant
extracts as literal data + pure functions; nothing required human
transcription. For the *module that carries the kernel* — **50%** (10 of 20
top-level functions): the transition wrappers that construct new immutable
records go through pydantic `model_validate`/`model_dump`/`model_copy` and the
wall clock, and those are precisely the parts Aeneas cannot cross mechanically.
The kernel's *decisions* translate; its *enforcement* does not.

**What semantic features break Aeneas applicability?** (measured on the module)
Pydantic record validation/reconstruction (no Rust-native counterpart — the
dominant breaker, 8 of the 10 untranslatable functions touch it directly or by
delegation); impure wall-clock reads (`_now` — translation-shaped only after an
explicit clock parameter refactor); `Any`-typed JSON evidence
(`evidence_values_equal` has no Charon-representable type); and domain
exceptions with payloads (encodable as `Result`/panic, but the callers'
`?`-plumbing is a mechanical rewrite, not a semantic translation). What does
*not* break it: the BFS with an explicit parent map, static `&'static [..]`
tables, total matches over fieldless enums — the Rust artifact is deliberately
inside that envelope.

**How much proof/model maintenance does ordinary evolution impose?**
The harness turns the question into a measured proxy: each production table
edit must be mirrored into two artifacts (Lean, Rust) or CI fails naming the
drifted row (`lean run row drift at <status>`); any structural change to how
the tables are defined (literal → computed) or any new function in
`lifecycle.py` fails the extraction/classification loudly. So the floor is
**two artifact edits per lifecycle-table edit, enforced** — cheap but
non-zero, and it lands on whoever touches the lifecycle, which is the honest
maintenance shape. What this head cannot measure is proof repair cost: that
requires a Lean toolchain (trigger recorded below; expected effort for the
current five theorems is well under a day for a proof engineer, since each
proof is `cases`/`decide`-shaped over a 9-constructor enum).

**Does this find or prevent a defect class not already well-covered by
property/model/concurrency testing?** None demonstrated. No Lean proof ran, so
no defect was found; and the kernel's invariants (terminal absorption, no
self-loops, terminal reachability, path legality/shortness/determinism) are
already machine-checked here as Python duals, adjacent to formal/ I31's
stateful property testing (#882) and the explicit-state model checker (#918).
A checked Lean kernel's marginal value is *re-verification under an
independent checker with a stronger metalogic* — valuable if the kernel grows
rules a table cannot express (e.g. earned completion over latest-NodeRun
state, ADR-082426-19ed's rule), which is exactly the recorded next
formalization step, not a present defect class.

**Is a Rust boundary justified by product/runtime value independent of
verification?** No. The kernel is a few hundred bytecodes of dict/BFS work on
a path already dwarfed by I/O; a safe-Rust sibling would add a second
implementation, an FFI boundary, and a second defect surface for zero runtime
value. The Rust artifact here is a translation-candidate prototype, not a
boundary proposal, and this research proposes no migration (per the issue's
own constraint).

**Can generated/proved artifacts be kept synchronized without creating a
second authority?** Yes, by direction of derivation, and the harness
demonstrates the shape: the production module is the only authority; the
Lean/Rust artifacts are *projections* re-equated against it on every test run.
The forbidden shape — artifacts that production is then edited to match, or a
checked-in "reference table" that can drift silently — cannot arise here
because the harness writes nothing and owns nothing. A future checked-in Lean
kernel must keep the same direction: derived from, and re-checked against, the
production source, never the reverse.

## Cost comparison against the other M8-A techniques

| | formal/ Hypothesis models (#410 suite, I31 et al.) | #882 stateful effect-idempotency testing | #918 explicit-state model checking | **#897 Lean/Rust kernel (this)** |
|---|---|---|---|---|
| Checks against | the real code | the real code + oracle models | hand-written abstract models | projections equated to the real code's tables |
| Assurance strength | randomized exploration, oracle-encoded invariants | same + mutant-verified unique yield | exhaustive over a bounded abstract state space | **potentially highest** (independent checker, stronger metalogic) — *unrealized here* (no toolchain run) |
| Fidelity boundary | imports production directly | imports production directly | abstraction is human judgment, replay-checked | extraction is mechanical for tables; enforcement code stays outside the model |
| CI cost | ~seconds per model, runs per PR | ~5s CI profile | one test module, sub-second | one test module, ~0.4s |
| Maintenance | model follows code by import | model follows code by import | models re-validated by hand-checked fixtures | 2 artifact edits per table edit, drift fails loudly; proof repair unmeasured |
| New defect class found at this head | I31: 2/5 mutants unique | race windows + harness vacuity | defect shapes rediscoverable on hand-checked models | none (nothing ran beyond the equivalence machinery) |
| Disposition | canonical evidence infrastructure | GRADUATE-class evidence (registered I31) | WATCH | **WATCH** |

Reading: this technique's differentiator is *proof reuse across evolution*
(check once, re-check forever, independently of pytest's process semantics) —
a real differentiator the other three do not offer — but it is gated on a
toolchain this repo does not have, and at this head it adds no defect-detection
yield the cheaper techniques lack.

## Trust boundary

The Lean kernel/checker, not any model's output — and not this harness — would
be the trust boundary for accepted proofs, exactly as the issue requires:
Leanstral (or any autoformalization assistant) is an accelerator whose output
is draft text until the Lean checker accepts it, and even a checker-accepted
kernel is advisory evidence for MAIstro: it would model — not replace — the
production decision, which stays owned by `maistro-core`'s runs package under
ADR-081226-a66b. Nothing in this change reads or writes a Goal, a Run
authority, a routing decision, or a Warden/HITL/delegation control. No Lean
artifact is a release dependency; no adoption routes anywhere from here.

## Disposition

- **WATCH** — the equivalence and measurement machinery is real, cheap (~0.4s
  CI), and already load-bearing against silent artifact drift; but no Lean
  proof was machine-checked, no Rust crate was built, no Aeneas translation
  ran, and Leanstral was not exercised. The external pipeline is not ready
  *in this repository's deterministic evidence path*, and unverified proof
  sketches must not be read as assurance.

  Reassessment triggers (move to INCUBATE on the first, GRADUATE only on the
  second's evidence):
  1. `elan` (Lean 4) available in CI: check `LEAN_KERNEL`'s five theorems and
     repair the sketches (expected under a day). A clean check = INCUBATE.
  2. An ordinary evolution window with a checked kernel in place: measure
     proof/artifact maintenance on a real lifecycle-table change and whether
     the kernel finds or prevents a defect class the property/model suites do
     not (the next formalization target is earned completion over
     latest-NodeRun state). Also worth one run when Charon/Aeneas can translate
     the extracted kernel mechanically, replacing the analytic evaluation.
  3. REJECT if a checked kernel still shows no yield beyond the existing
     property/model suites after one real evolution window at acceptable
     maintenance cost.
