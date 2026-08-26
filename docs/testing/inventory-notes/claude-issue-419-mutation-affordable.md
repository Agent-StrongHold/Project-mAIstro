---
inventory-delta:
  tests/: +28
---
# claude-issue-419-mutation-affordable

Twenty-eight new node IDs: 16 in `test_mutation_filter_annotations.py`, 6 in
`test_mutation_packet_safety.py`, 6 appended to `test_mutation_targets.py`.
Nothing removed or reparametrised.

## Why mutation testing needed this before it needed anything else

`mutation.yml` is parked pending self-hosted capacity, so none of this ran in
CI. I ran cosmic-ray locally against one gate to find out what a packet
actually costs: 206 mutants, ~5.9 s each at 4 workers, ~20 min for the file —
inside `DEFAULT_PACKET_SECONDS`. The budget was never the problem. What the
budget was being *spent on* was.

## `test_mutation_filter_annotations.py` (16)

Under `from __future__ import annotations` an annotation is a string. Python
never evaluates it, so `-> Path | None` yields six mutants — Add, Mul, Mod,
RShift, LShift, BitAnd — that survive by construction, cost a full test-command
run each, and land in the survivor list to be triaged as "equivalent" every
time. Six of the first seventeen survivors measured were that one line.

Counted by AST: 1,861 union nodes in annotation position across the 682 files
under `packages/*/src` carrying the future import. ~11,166 unkillable mutants,
~18 hours of runner time, zero signal.

`TestWhatMustNotBeSkipped` is the half that matters. Skipping a mutant a test
*could* have killed silently lowers the bar, and the sharpest case is
`test_a_runtime_union_is_not_an_annotation`: `isinstance(node, A | B)` **is**
evaluated and its mutants **are** killable. Same operator, same file,
distinguished only by position — which is why this is a positional filter and
not a regex over operator names, the only thing cosmic-ray ships.

`TestAgainstTheRealTree` asserts both directions on one real file, because a
filter that gets one right and the other wrong is worse than none.

`test_a_mutation_straddling_an_annotation_edge_is_not_skipped` records a
deliberate strictness: wholly inside, not partly. No straddling mutant has been
observed; the rule exists so an unobserved shape fails toward *running* the
mutant rather than silently dropping it.

## `test_mutation_targets.py` (+6)

`scripts/` resolved to nothing, so every gate — the code deciding whether
anything else may merge — was the one body of Python mutation could not reach.
The same blind spot #257 closed for diff coverage, one instrument later.

`test_a_script_without_a_mirror_test_is_skipped_not_widened` keeps the rule the
module was built on: there is no ancestor to widen to, `tests/` is the whole
root suite, and mutating one script against all of it is exactly the unbounded
scope that produced the original 30-minute timeout.

## `test_mutation_packet_safety.py` (6)

Cosmic-ray mutates in place and restores between mutants. Interrupt it and the
mutation stays on disk. This happened **three times** while measuring #419:

    if pkg.is_dir() and (pkg // "__init__.py").is_file():   # was /
    for alias in []:                                        # was node.names
    if pkg.is_dir() or (pkg / "__init__.py").is_file():     # was and

Each time in the import-resolution gate, and each time noticed only because a
test run afterwards went red. The third arrived *after* a `git checkout`,
because the run I believed had finished was still alive — the wrapper shell had
exited, the exec had not.

That is the shape worth guarding: a leftover mutant reads as deliberate. It is
small, plausible and syntactically valid, and a reviewer would have to know the
original to question it.

`test_it_restores_bytes_not_git_state` pins the mechanism. Restoring from git
would work here and silently revert whatever else the developer had uncommitted.

## What is not in this change

No baseline entry. `quality/mutation-baseline.json` still has `entries: {}`,
and arming the ratchet needs a *complete* run of a source. Every attempt in
this container stopped short — cosmic-ray's `exec` did not resume a partially
complete session, so a killed run could not be continued, only restarted.
Recording a kill rate from a partial run would be exactly the unearned claim
the rest of this repository's gates exist to prevent.

Worth noting for the scheduler: if a packet exceeds its budget it cannot be
resumed, only re-run. That is an argument for the filter and for tight per-file
scoping, not for a bigger budget.
