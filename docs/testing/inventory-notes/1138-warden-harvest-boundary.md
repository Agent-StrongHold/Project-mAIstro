---
inventory-delta:
  packages/maistro-rsi/tests: +35
---
# Issue #1138 Warden harvest boundary

Adds collected cases covering recursive RSI harvest admission: ordinary and
structured payload forms, model-call refusal, unavailable-policy fail-closed
behavior, audit correlation/redaction, canonical event persistence, digest
evidence, nested keys, synchronous active-loop refusal, and saved-patch resume
refusal for hostile or unavailable Warden policy.

The repair pass adds `test_non_production_reachability.py` (13 node IDs):
RSI's activation defaults stay pinned to disabled/non-production-reachable
until #552's M5 containment gates. No engine product package may import the
`maistro_rsi` surface; the only product references are the Conductor's two
execution-policy-gated seams; the HTTP run gate stays literally fail-closed
(`IN_PROCESS_ISOLATION_AVAILABLE is False`, and `start_run` resolves
`require_isolation()` before dispatch). Scanner-sensitivity cases prove the
static scans flag every import form (including dynamic `import_module` /
`__import__`) and the activation flips, so a green run is evidence rather
than a vacuous pass.

The second repair pass adds 6 more node IDs closing the residual audit-
correlation and adversarial-probe gaps: the real maistro-evolve swebench
seam is pinned as guarded by the cycle-installed wrapper (plus a control
proving the seam itself does not scan, so the wrapper is load-bearing);
hostile builder system prompts, scout sources, judge diffs, and proposer
hypotheses are each refused before their model callable with durable,
campaign-correlated audit records; resume refusals now also assert the
audit trail carries campaign/repository/base correlation. Mutation
validation executed: disabling the runner guard, the scout scan, the
builder system-prompt admission, or the resume admission each fails the
adversarial tests (2/1/1/2 failures respectively).

Revalidated at merge head `11b1a55ea` (develop base `84d937add`, no test
delta): the develop merge touched no `maistro-rsi`/`maistro-evolve` file and
left `WardenVerdict` unchanged (only `Violation`/`AuditEntry` moved to
canonical types). Full battery re-executed: 756 rsi + 645 evolve tests pass,
ruff check/format clean, suite-inventory/security-inventory/reachability
(+dispositions, provenance) gates pass. Mutation checks re-executed at this
head: removing the runner guard fails 2 tests; ignoring the resume-patch
admission fails 2 tests; both mutations reverted with the tree byte-verified
clean. One unrelated pre-existing upstream failure
(`maistro-core/tests/security/test_log_redaction.py::test_install_is_idempotent`)
reproduces on canonical develop and is out of scope for this lane.

Revalidated at merge head `e9d16cdcc` (develop base `411a21856`, no test
delta): that develop merge added only a CHANGELOG entry, the #44 container-
resolver inventory note, and a maistro-core composition test — it touched no
`maistro-rsi`/`maistro-evolve` file. Full battery re-executed at this head:
756 rsi tests pass, 645 evolve tests pass (6 skipped), 13
non-production-reachability node IDs pass, 46 targeted adversarial tests
(shape relocation, hostile resume, unavailable policy, correlation/redaction)
pass, ruff check/format clean, suite-inventory (13 suites), security-inventory
(59 paths), and the four reachability gates pass. Mutation checks re-executed
at this head: removing the runner injected-llm_call guard fails
`test_injected_llm_call_is_guarded_for_both_genome_evals` +
`test_llm_call_reaches_evaluate_genome`; ignoring the resume-patch admission
fails `test_hostile_resumed_patch_is_refused_before_apply` +
`test_unavailable_warden_refuses_resumed_patch`; both mutations reverted with
`git status --porcelain` empty and the files byte-identical to HEAD.

Repair round at head `43822db55` (develop base `8bb344e32`): independently
re-derived the seam inventory instead of trusting prior claims — every model
invocation seam in `maistro-rsi` is boundary-guarded: `gateway.py` (scan before
HTTP I/O), `runner.py` (injected `llm_call` wrapped with `guarded_async_call`),
`local_loop.py` (builder system prompt + `WardenGuardedCallable` transcript
scan, saved-patch resume admission, hyper-mutation prompt admission, regression
judge diff admission), `autorun.py` (proposer hypothesis/insights admission),
`__main__.py` (hyper-mutator goal/target/prompt admission), `scout.py` (both
scout calls), `benchmarks/swebench_pro.py` (guarded model call + genome system
prompt). `free_router.py` sends only a literal ping — not a harvest seam;
`harvest.py` is promotion-side grouping (#302). Full battery re-executed at
this head: 756 rsi + 645 evolve tests pass, ruff check/format clean,
suite-inventory/security-inventory/reachability (+dispositions, provenance)
gates pass. Mutation evidence re-executed by this round: replacing the runner
guard body with a direct inner call fails
`test_injected_llm_call_is_guarded_for_both_genome_evals`; gating the resume
admission off fails `test_hostile_resumed_patch_is_refused_before_apply` +
`test_unavailable_warden_refuses_resumed_patch`; both reverted, tree
byte-identical to `43822db55` (`git status --porcelain` empty, all 26
runner+resume tests green again).

Revalidated at merge head `b96ce7b36` (develop base `60862b6c`, no test
delta): that develop merge touched no `maistro-rsi`/`maistro-evolve`/
`maistro.security` file. This round independently re-derived the seam sweep
instead of trusting prior claims — every model seam re-read at this head:
`gateway.py` (scan before HTTP I/O), `runner.py` (injected `llm_call` wrapped),
`local_loop.py` (builder system prompt, saved-patch resume, hyper-mutation
prompt, regression-judge diff), `autorun.py` (proposer, prompt, ledger-at-use),
`__main__.py` (mutator, harvest), `scout.py` (both calls), `regression_judge.py`,
`benchmarks/swebench_pro.py`; `free_router.py` verified to send only a literal
ping and `quota_burn.py` only model listing — neither carries harvest content.
Full battery re-executed at this head: 756 rsi + 645 evolve tests pass, ruff
check/format clean, suite-inventory (13 suites), security-inventory (59 paths),
reachability (+dispositions, provenance) gates pass. Mutation evidence
re-executed by this round at this head: replacing `llm_call = guarded_llm_call`
with a pass-through of the injected call fails
`test_injected_llm_call_is_guarded_for_both_genome_evals` +
`test_llm_call_reaches_evaluate_genome`; deleting the resume admission check in
`_load_saved_patches` fails `test_hostile_resumed_patch_is_refused_before_apply`
+ `test_unavailable_warden_refuses_resumed_patch`; both restored from byte
backups with `git status --porcelain` empty and `git diff` empty afterwards.

Revalidated at merge head `04d33d5c3` (merge of develop `60862b6c5` into the
branch; no test delta, `git diff 369279ab6..HEAD -- packages/maistro-rsi` is
empty). The merge's only security-surface change is additive: `maistro.security`
gains a `WARDEN_POLICY_VERSION = "warden-code-v1"` class attribute on the
canonical `Warden` detector plus a canonical `composition.py` — detection
behavior is unchanged and the rsi-harvest boundary keeps its own audit-only
`warden-rsi-harvest-v1` identifier (detector mechanism stays code-owned). This
round re-derived the seam inventory at this head (all seams listed above
re-read, plus `autorun.py`'s direct `httpx.post` confirmed behind the proposer
`scan_sync` admission and `code_fixer.py` confirmed to reach models only via
the guarded `make_builders_apply_patch` builder path). Executed evidence:
756 rsi + 645 evolve + 58 conductor `test_rsi_execution_containment.py` tests
pass, 66 `ac`-marked #1138 tests pass, all 13 non-production-reachability node
IDs pass, ruff check/format clean, suite-inventory / security-inventory /
reachability (+dispositions, provenance) gates pass. Mutation evidence
re-executed at this head: disabling the runner guard fails
`test_injected_llm_call_is_guarded_for_both_genome_evals` +
`test_llm_call_reaches_evaluate_genome`; gating the resume admission off fails
`test_hostile_resumed_patch_is_refused_before_apply` +
`test_unavailable_warden_refuses_resumed_patch`; both files restored from byte
backups, `git status --porcelain` empty and both files `cmp`-identical to HEAD.

Revalidated at `36d212a6c` (independent verifier round; diff vs `04d33d5c3`
is docs-only). Re-inspected all three originally reported bypass seams at this
head: `runner.py` wraps every injected `llm_call` in `guarded_llm_call`
(scan precedes benchmark scoring), `local_loop.py:1665-1677` scans resumed
patches via `scan_sync` before `_git_apply` (reached from `run():2569`), and
`harvest_boundary.py` fails closed on both `warden_unavailable` and
`audit_unavailable`. Seam sweep re-derived: autorun proposer `scan_sync`
precedes the direct `httpx.post`; `free_router` sends a literal ping plus
operator-controlled alias registration only; `quota_burn` only GETs model
listings; `swebench_pro` scans candidate-controlled genome fields before the
system prompt reaches the model. Executed: full `packages/maistro-rsi`
suite (756 passed), 58 conductor containment tests, ruff check/format
repo-wide clean, reachability + dispositions + provenance gates OK.
Mutation evidence independently re-executed at this head with byte backups:
runner-guard removal fails 2 adversarial tests, resume-admission removal
fails 2 adversarial tests; both files restored byte-identical
(`git status --porcelain` empty) and post-restore tests pass (26 passed).
Known residual (unchanged, non-blocking): a bare `WardenHarvestBoundary()`
with no sink (tests and the `swebench_pro` proxy path) records audit via
logging only; every production composition root wires `JsonlAuditSink` or
an event-store sink, and the missing-sink path still fails closed on scan.

Repair revalidation at merge head `9bb626b178` (develop base `03c8ba83a`,
prior repair head `8adc2cacc` is an ancestor; `git diff 8adc2cacc..HEAD --
packages/maistro-rsi packages/maistro-core/src/maistro/security` is empty —
the merge touched only graph/durable-runs, reactor, and chat-execution
surfaces). No test delta. Independently re-derived the seam sweep at this
head: `gateway.py` (scan before HTTP I/O), `runner.py` (injected `llm_call`
wrapped), `local_loop.py` (builder prompt, saved-patch resume, hyper-mutation
prompt, regression-judge boundary), `autorun.py` (proposer scan precedes the
direct `httpx.post`, prompt executor, ledger-at-use), `__main__.py` (mutator
goal/target/prompt + harvest manifest), `scout.py` (both calls),
`regression_judge.py`, `benchmarks/swebench_pro.py` (genome fields before
system prompt); `free_router.py` (literal ping) and `quota_burn.py` (model
listing GET) carry no harvest content. Executed: ruff check/format repo-wide
clean; 756 rsi tests pass; 13 non-production-reachability node IDs pass;
58 conductor containment tests pass; 66 `ac`-marked #1138 tests pass; all
four reachability gates + `check-security-inventory.py` +
`check-suite-inventory.py` (13 suites) pass. Mutation evidence re-executed
independently at this head with byte backups: replacing `llm_call =
guarded_llm_call` with the raw injected call fails
`test_injected_llm_call_is_guarded_for_both_genome_evals` +
`test_llm_call_reaches_evaluate_genome` (2 failed); gating the resume
admission off in `_load_saved_patches` fails
`test_hostile_resumed_patch_is_refused_before_apply` +
`test_unavailable_warden_refuses_resumed_patch` (2 failed); both files
restored byte-identical (`cmp` vs backups, `git status --porcelain` empty)
and the 4 adversarial tests pass again post-restore.

Revalidation at merge head `36a7a1f8dd` (develop base `5eeac0734b`; prior
repair head `4a4d91d66b`; `git diff 4a4d91d66b..HEAD -- packages/maistro-rsi
packages/maistro-evolve packages/maistro-core/src/maistro/security` is empty —
that merge added only compliance-evidence scripts/tests). Independently
executed evidence at this head: an out-of-tree adversarial probe drove
`RsiCycle.run` with a malicious candidate system prompt through the REAL
`proxy_swebench` benchmark — all 10 candidate samples were refused with the
truthful `error: RSI harvest content was not admitted (blocked)` outcome
(score 0.0) and the payload never reached the model callable; the run's
`JsonlAuditSink` wrote 40 durable records (20 admitted / 20 blocked) carrying
workspace/run/source_repository/source_base/candidate_id/policy_version/digest
and zero payload or credential text. Full battery re-executed: 756 rsi + 645
evolve (6 skipped) tests pass, 66 `ac`-marked #1138 tests pass, 13
non-production-reachability node IDs pass, 58 conductor containment tests
pass, ruff check/format repo-wide clean, suite-inventory (13 suites),
security-inventory (59 paths) and all four reachability gates pass. Mutation
evidence independently re-executed with byte backups: removing the runner
guard call fails `test_injected_llm_call_is_guarded_for_both_genome_evals`
(1 failed; the plumbing-only `test_llm_call_reaches_evaluate_genome` passes
under this mutation — earlier notes overstated that count), and gating the
resume admission off fails `test_hostile_resumed_patch_is_refused_before_apply`
+ `test_unavailable_warden_refuses_resumed_patch` (2 failed); both files
restored byte-identical (`cmp` vs backups, `git status --porcelain` empty)
and all 26 runner+resume tests green post-restore. Push-blocking note: the
earlier non-fast-forward is resolved locally — `origin/auto-1138` (`8b7c8fb16`)
is an ancestor of this head, so a future push is a fast-forward.

Revalidation at merge head `9d943a8a9` (develop base `2c8022fe8`, no source
delta vs prior revalidation — `git diff` between this head and the prior
round's checked tree is confined to the merge/docs). Independent verifier
round: driver checks (uv sync, ruff check, ruff format --check, 166 targeted
rsi tests, suite inventory) all green per job logs; the 166 targeted tests
re-executed locally by this round also pass (19.2s). Out-of-tree adversarial
probes re-executed at this head, all passing: (1) one payload relocated across
plain text / nested structured value / attacker-controlled key / filename /
commit-message / diff-hunk text is blocked in every shape by the canonical
Warden and `admit()` raises; (2) `Warden=None` fails closed with truthful
`warden_unavailable`, correlated (workspace/project/run/attempt/campaign/
candidate/base/head/policy_version) and credential-redacted audit record;
(3) the REAL `proxy_swebench` seam behind the cycle-installed
`guarded_async_call` wrapper refuses a malicious candidate system prompt —
inner model callable never invoked, score 0.0; (4) a hostile tool-schema
description in call kwargs is refused before the model. Seam re-enumeration at
this head confirms every model/context seam guarded: gateway.py (scan before
HTTP I/O), runner.py (injected llm_call wrapped), local_loop.py (builder
system prompt + WardenGuardedCallable transcript scan, saved-patch resume
admission before `git apply`, hyper-mutation prompt, scout caller,
regression-judge diff), autorun.py proposer, `__main__.py` hyper-mutator,
scout.py (both calls), swebench_pro.py (guarded model call + genome fields).
`free_router.py` (literal ping) and `harvest.py` (promotion-side grouping,
#302) confirmed non-seams. Quarantine independence re-pinned:
`selfbranch.py` gates PR creation on an affirmative `quarantine_verdict.cleared`
(a missing check is DENY), unaffected by any Warden verdict. Closure-keyword
review: PR #1446 body says "Refs #1138" and no commit in
`2c8022fe8..9d943a8a9` contains fixes/closes/resolves — no premature issue
closure. Residual observation (non-blocking): the defense-in-depth boundary
inside `benchmarks/swebench_pro.py` carries only `candidate_id` correlation
and no durable sink; refusals at that secondary layer surface in the
EvalResult metadata (`warden_admission`) and structured logs, while the
primary RsiCycle/gateway layer persists correlated Jsonl audit — acceptable
because content admission still fails closed and the truthful outcome is
recorded, but a future pass could thread `audit_sink`/`correlation` through
that layer too. Push-block resolution verified locally: `origin/auto-1138`
(`8b7c8fb16`) is an ancestor of this head (fast-forward when pushed; pushing
remains a writer/driver action).

Independent verifier revalidation at `c15128b11` (develop base `2c8022fe8`;
`git diff 9d943a8a9..HEAD` excluding this notes file is empty — docs-only
round). Re-executed by this round: the 166 targeted rsi tests pass (19.1s);
`ruff check .` clean; `check-suite-inventory.py --suite
packages/maistro-rsi/tests` OK (756 recorded). Fresh out-of-tree probes
(/tmp, real `Warden`, no tree edits), 16/16 pass: one payload relocated
across plain text / nested value / attacker-controlled mapping key /
filename / commit-message / diff text is `blocked` in every shape; `Warden=None`,
a raising scanner, and `scan_sync` inside a running loop each fail closed with
truthful `warden_unavailable`; clean content is admitted with a correlated
audit record (workspace/project/run/attempt/source repo+base+head/campaign/
candidate/policy_version/digest present; URL credentials stripped; no payload
content in the audit file); `guarded_async_call` refusal invokes the inner
model callable zero times while clean messages flow through. Resume-path
probe on a real git baseline: a saved patch whose filename AND diff carry the
payload is refused before `_git_apply` (`git status --porcelain` empty, no
commit, `EVIL` absent), with a durable `admitted=false` JsonlAuditSink record.
Quarantine independence re-read at this head: `selfbranch.py` requires an
affirmative `quarantine_verdict.cleared` to open a PR (missing check = DENY).
Prior push block fully resolved: `origin/auto-1138` now equals `c15128b11`
(fast-forward; pushing remains a writer/driver action). Residual unchanged
(non-blocking): `benchmarks/swebench_pro.py` secondary boundary keeps
candidate_id-only correlation and no durable sink; the primary RsiCycle/
gateway layer persists durably and that layer still fails closed.

Repair-round revalidation at `c88608dd` (develop base `2c8022fe8`;
`git diff c15128b11..c88608dd` touches only this notes file — code identical
to the prior verified head, so the boundary code re-validated unchanged).
Re-executed by this round: full `packages/maistro-rsi/tests` suite 756 passed
(58.4s); `ruff check .` and `ruff format --check .` clean;
`check-suite-inventory.py --suite packages/maistro-rsi/tests` OK (756
recorded). Fresh out-of-tree probe set (/tmp, real `Warden`, no tree edits),
16/16 pass: payload mobility across plain text / nested value /
attacker-controlled mapping key / filename / commit-message / diff text all
`blocked`; fail-closed on `Warden=None`, a raising scanner, `scan_sync` inside
a running loop, AND a raising audit sink (`audit_unavailable`, admitted
false); `WardenGuardedCallable` refusal raises `HarvestInputRefused` with the
inner model callable invoked zero times, clean traffic flows, and a hostile
tool description smuggled through call kwargs is also refused; audit record
carries workspace/project/run/attempt/repo+base+head/campaign/candidate/
policy_version/digest with URL credentials (`user:SECRET-TOKEN@`) stripped and
zero payload text. Explicit re-runs: guarded/load-bearing/seam control tests
(3 passed — the control proves the raw seam leaks the payload, so removing
the wrapper fails the adversarial test), resume+boundary tests (19 passed),
non-production reachability (13 passed). Seam sweep at this head: every
model-call site in the package is boundary-guarded — including the
`swebench_pro` cross-file judge, which receives the already-guarded
`model_call` — and every `Warden()` construction is unconditional (no
isolation- or environment-conditional allow-all). Residual unchanged
(non-blocking): `swebench_pro.py:203-210` secondary boundary keeps
candidate_id-only correlation and a logging-only sink; it fails closed
independently of audit and the outer RsiCycle wrapper (runner.py:215-239)
durably audits the same calls.

Independent verifier round at `aa664d20` (develop base `2c8022fe8`; code
identical to the prior verified head — `git diff c15128b11..aa664d20` touches
only this notes file). The three originally-reported bypass seams were
re-inspected at this head and are fixed: `runner.py:215-239` wraps every
injected `llm_call` in `guarded_llm_call`/`guarded_async_call`;
`local_loop.py:1641-1677` scans resumed patches (`scan_sync`) before
`_git_apply` and skips refused patches; `harvest_boundary.py` fails closed on
`warden_unavailable`, a raising scanner, a raising audit sink, and a
`scan_sync` invoked inside a running event loop. Executed by this round:
166 targeted rsi tests (20.2s), full rsi suite 756 passed (45.5s), 645 evolve
tests (6 skipped), 58 conductor containment tests, 13 non-production-
reachability node IDs, `ruff check .` / `ruff format --check .` clean,
`check-suite-inventory.py` OK (756). Fresh out-of-tree probes (/tmp, real
`Warden`, no tree edits): (1) one payload relocated across plain text / nested
value / attacker-controlled mapping key / filename / commit-message diff hunk
/ review comment is `blocked` in every shape; (2) `Warden=None`, a raising
scanner, a raising audit sink (`audit_unavailable`), and in-loop `scan_sync`
each refuse with a truthful outcome; (3) audit records carry
workspace/run/campaign/candidate/policy_version/digest, strip URL credentials
(`https://user:SECRET@` → host-only), and contain zero payload text;
(4) `WardenGuardedCallable` refusal invokes the inner model callable zero
times, clean traffic flows, and a hostile tool description in call kwargs is
refused; (5) end-to-end: `RsiCycle.run` with an injected llm_call and a
malicious candidate system prompt, scored through the REAL
`maistro-evolve` `run_swebench` — score 0.0, truthful `not admitted` outcome,
30 durable `JsonlAuditSink` records with correlation; (6) resume probe on a
real git baseline: a saved patch whose filename AND diff carry the payload is
refused before `_git_apply` (HEAD unchanged, no evil file/content, benign
patch still applied, durable blocked record with campaign/repo/base/policy
correlation). Mutation evidence independently re-executed with byte backups:
bypassing the runner guard fails
`test_injected_llm_call_is_guarded_for_both_genome_evals` +
`test_llm_call_reaches_evaluate_genome`; gating the resume admission off fails
`test_hostile_resumed_patch_is_refused_before_apply` +
`test_unavailable_warden_refuses_resumed_patch`; both files restored
byte-identical to HEAD (`cmp` vs backups AND `git show HEAD:`),
`git status --porcelain` empty. Seam sweep independently re-derived at this
head: gateway.py (scan before HTTP I/O), runner.py (injected llm_call
wrapped), local_loop.py (builder system admission + `WardenGuardedCallable`
transcript scan incl. tool results, saved-patch resume, hyper-mutation prompt,
regression-judge diff), autorun.py (proposer scan precedes the direct
`httpx.post`, prompt executor, ledger-at-use), `__main__.py` (mutator
goal/target/prompt + harvest manifest), scout.py (both calls),
`regression_judge.py` (target+diff), `benchmarks/swebench_pro.py` (genome
fields before system prompt; cross-file judge receives the already-guarded
call); `free_router.py` (literal ping + operator-controlled alias
registration), `quota_burn.py` (models-listing GET), and `harvest.py`
(promotion-side grouping, #302) carry no harvest content. Every `Warden()`
construction is unconditional; `None` fails closed. Quarantine independence
re-read at this head: `selfbranch.py:161-170` requires an affirmative
`quarantine_verdict.cleared` (missing check = DENY) — Warden verdicts do not
authorize merge/promotion. Closure-keyword review: PR #1446 body says
"Refs #1138" and no commit in `2c8022fe8..aa664d20` contains
fixes/closes/resolves. Residual unchanged (non-blocking, documented above):
the bare no-sink `WardenHarvestBoundary()` defense-in-depth paths
(e.g. `swebench_pro.py` secondary layer) audit via logging only, still fail
closed independently of audit, and every production composition root wires a
durable `JsonlAuditSink`.
