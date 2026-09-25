---
inventory-delta:
  formal/: +256
  tests/: +3
---
# Issue 341 formal security conformance

The formal dangerous-tools model consumes the independently governed
`formal/fixtures/security_oracle.json` instead of importing implementation
constants or checking source-token counts. Its 41 adversarial command cases
cover the 22 detector rules with per-rule narrowing witnesses (flag variants,
alternate targets, alternate syntax) including the `rm -rf ~` weakening
witness; benign cases, tool cases, path cases, property samples, runtime
deletion mutation checks, benign-context laundering checks, and
production-enforcement (`MicroVMSandbox.exec`) refusal checks add 256
collected formal nodes. The base-diff independence gate and its three tests
add 3 nodes under `tests/`.

Mutation evidence (all fail `pytest formal/models/test_dangerous_tools.py`):
21-of-22 pattern deletion (189 failed), `rm\s+-rf\s+[/~]` → `rm\s+-rf\s+/`
weakening (6 failed), `sudo\s+` → `sudo\s+apt\s+install` narrowing (7 failed),
removing the deny check from `MicroVMSandbox.exec` (41 failed), and a
safe-prefix shadowing short-circuit in `is_dangerous_command` (54 failed).

Independent re-verification (head `3f4be1b`, sandboxed mutations outside the
worktree): suite 256/256 green; full required-CI equivalent
`pytest formal/models/ -q --hypothesis-seed=0` → **664 passed** with
pgvector:pg18 + `alembic upgrade head` + `maistro-evolve` installed. Mutations
re-executed and all fail: rm-weakening → 6 failed, `sudo` narrowing → 7 failed,
21-of-22 deletion → 189 failed, `MicroVMSandbox.exec` deny-check removal →
41 failed, safe-prefix shadow → 110 failed (broader prefix set than the
documented 54-case variant). `scripts/check-formal-oracle-independence.py`:
bootstrap OK against the develop base (oracle absent there), exit 1 on a
simulated later oracle+implementation co-change. `uv run ruff check .` clean.

Re-verification at head `4696527` (worktree unmodified throughout; mutations
executed in a PYTHONPATH-shadowed copy under `/tmp`, whose unmutated baseline
also reproduces 256/256): `uv run ruff check .` and
`uv run ruff format --check .` clean; targeted suite 256/256; **full
required-CI equivalent `pytest formal/models/ -q --hypothesis-seed=0` → 664
passed** against live pgvector:pg18 after `alembic upgrade head`
(closes the earlier "complete required-CI formal run UNVERIFIED — no local
PostgreSQL" finding). Mutations re-executed, all fail the required suite:
rm-weakening `rm\s+-rf\s+[/~]`→`rm\s+-rf\s+/` → 6 failed; 21-of-22 deletion
(one detector retained) → 189 failed; `MicroVMSandbox.exec` deny-check removal
→ 41 failed; safe-prefix shadow short-circuit in `is_dangerous_command` →
89 failed; `sudo\s+`→`sudo\s+apt\s+install` narrowing → 7 failed.
`tests/test_check_formal_oracle_independence.py` → 3 passed; the real script
end-to-end in a scratch git repo: bootstrap base (oracle absent) exit 0,
later oracle+implementation co-change exit 1, oracle-only change exit 0.
`formal-conformance` remains a required status check
(`.github/branch-protection.json`); the develop base `8bb344e` carries no
oracle, so this PR legitimately takes the checker's bootstrap path.

Independent verifier pass at head `b7356d5` (this lane's review head; worktree
unmodified — all mutations sandboxed outside it): targeted
`pytest formal/models/test_dangerous_tools.py -q --hypothesis-seed=0` →
**256 passed**; full required-CI equivalent `pytest formal/models/ -q
--hypothesis-seed=0` → **664 passed** against a dedicated pgvector:pg18
container after `alembic upgrade head` (with `maistro-core` and
`maistro-evolve` installed as the required workflow does — the bare
`uv sync --extra dev` venv lacks `maistro_evolve`, which the CI job installs
explicitly). `uv run ruff check .` clean in the same pass. Mutation battery
re-executed via PYTHONPATH-shadowed copies under `/tmp` (shadow verified via
`patterns.__file__`; unmutated shadow baseline 256 passed):
21-of-22 raw-string deletion (one detector retained) → **189 failed** on the
exact required CI command; `rm\s+-rf\s+[/~]`→`rm\s+-rf\s+/` weakening →
**6 failed** (`remove-home` incl. the production `MicroVMSandbox.exec`
enforcement case). Oracle-independence gate exercised end-to-end: real script
on this PR → bootstrap exit 0 (oracle absent at develop base `8bb344e`,
verified via `git cat-file`); scratch-clone oracle-only change → exit 0;
scratch-clone oracle+implementation co-change (weakened oracle + pattern
rewrite) → **exit 1** with the co-change rejection.
`tests/test_check_formal_oracle_independence.py` → 3 passed.
Residual (unchanged, org-side): live GitHub rulesets require 0 approvals and
no code-owner review, so CODEOWNERS alone cannot stop a co-change PR — the
in-repo mechanical control is the required `formal-conformance` check running
`scripts/check-formal-oracle-independence.py`, which rejects the co-change
diff itself. Live GitHub CI green for this PR head remains UNVERIFIED (no push
permitted from verification).

Repair-phase validation at head `cc4b2ca` (worktree unmodified during
validation; mutations in a PYTHONPATH-shadowed symlink copy under `/tmp`,
shadow verified via `patterns.__file__`; unmutated shadow baseline 256
passed): `uv run ruff check .` and `uv run ruff format --check .` clean;
targeted `pytest formal/models/test_dangerous_tools.py -q --hypothesis-seed=0`
→ **256 passed**; full required-CI equivalent `pytest formal/models/ -q
--timeout=300 --hypothesis-seed=0` → **664 passed** against a dedicated
pgvector:pg18 container after `alembic upgrade head`, with `maistro_evolve`
importable as the workflow's explicit install provides. Mutations re-executed,
both fail: `rm\s+-rf\s+[/~]`→`rm\s+-rf\s+/` weakening → **6 failed**
(`remove-home` incl. the production enforcement case); 21-of-22 deletion
retaining only `sudo\s+` → **193 failed**. Oracle-independence gate:
real script at this head with `--base 8bb344e` → bootstrap exit 0; scratch
clone oracle-only change → exit 0; scratch clone oracle+implementation
co-change → **exit 1**; `tests/test_check_formal_oracle_independence.py` →
3 passed. `formal/extractors` and `formal/generated` remain absent with zero
references. No repair was required; no acceptance criterion regressed.

Independent acceptance verification at head `8c25ef4e` (worktree unmodified;
mutations in a `/tmp` shadow copy verified via `patterns.__file__`;
scratch-clone gate runs under `/tmp/clone`): targeted
`pytest formal/models/test_dangerous_tools.py -q --hypothesis-seed=0` →
**256 passed**; full required-CI equivalent `pytest formal/models/ -q
--timeout=300 --hypothesis-seed=0` → **664 passed** against a dedicated
pgvector:pg18 container on 127.0.0.1:54329 after `alembic upgrade head`, with
`maistro-evolve` installed as the workflow does; `uv run ruff check .` and
`uv run ruff format --check .` clean;
`tests/test_check_formal_oracle_independence.py` → 3 passed. Mutation battery
(all fail the suite, worktree untouched): rm-weakening `[/~]`→`/` → **6
failed** (`remove-home` incl. the production `MicroVMSandbox.exec` case);
21-of-22 deletion retaining only `sudo\s+` → **193 failed** on the exact
required-CI command; safe-prefix shadow short-circuit in
`is_dangerous_command` → **125 failed**; deny-check removed from
`MicroVMSandbox.exec` → **41 failed**. Gate end-to-end (real script, scratch
clone): oracle-only change vs PR head → exit 0; oracle+implementation
co-change → **exit 1**; this PR vs develop base `8bb344e` → bootstrap exit 0.
`formal/extractors`/`formal/generated` absent with zero references;
CODEOWNERS covers `/formal/fixtures/` and `/formal/SECURITY-CONFORMANCE.md`;
no closure keywords in PR body or branch commits. Residual: live GitHub CI
status for PR 1452 remains UNVERIFIED (push prohibited); org rulesets still
require 0 approvals — the in-repo mechanical control is the required
formal-conformance job rejecting the co-change diff itself.

Final independent pass at head `0a17390ce` (worktree clean at the exact lane
SHA; driver check logs again covered only uv-sync/ruff/format, so every
number below was executed in this pass): targeted
`pytest formal/models/test_dangerous_tools.py -q --hypothesis-seed=0` →
**256 passed**; full required-CI equivalent `pytest formal/models/ -q
--timeout=300 --hypothesis-seed=0` → **664 passed** against pgvector:pg18 on
127.0.0.1:5432 after `alembic upgrade head`, with `maistro-evolve` installed
as the workflow does (driver `uv sync` had removed it; CI-equivalent install
restored). Mutation battery, all in a `/tmp` PYTHONPATH-shadowed copy of
`maistro-core/src` (precedence proven via `patterns.__file__`/`microvm.__file__`;
worktree untouched): 21-of-22 deletion retaining only `sudo\s+` → **193
failed** on the exact required-CI command; rm-weakening `[/~]`→`/` → **6
failed**; safe-prefix shadow short-circuit in `is_dangerous_command` → **128
failed**; deny check removed from `MicroVMSandbox.exec` → **41 failed**. Gate
(real script, scratch clone at this head): bootstrap vs base `8bb344e` →
exit 0 (oracle absent at base); post-landing oracle-only change → exit 0;
oracle+implementation co-change → **exit 1**; unresolvable base → **exit 2**
(fails closed). `tests/test_check_formal_oracle_independence.py` → 3 passed;
`uv run ruff check .` / `uv run ruff format --check .` clean.
`formal/extractors`/`formal/generated` absent with zero references;
ADR-072/ADR-073/SPEC-190 all exist in-tree; no closure keywords in the PR
body or branch commits (sole regex hit is prose "closes the prior finding").
Verifier commits 4696527..0a17390c touch only this notes file.

Residuals (documented, not repaired — read-only review): (1) live GitHub CI
status for PR 1452 remains UNVERIFIED (push prohibited). (2) Org rulesets
require 0 approvals / no code-owner review / no last-push approval — outside
repo control; the in-repo mechanical control is the required
formal-conformance job, which rejects the co-change diff itself. (3) The gate
executes the candidate checkout's copy of
`scripts/check-formal-oracle-independence.py`; a candidate that rewrites the
script's logic in the same PR as oracle+implementation changes could neuter
it (visible in the diff, and script+oracle co-change alone is still exit 1),
but CODEOWNERS does not name `/scripts/check-formal-oracle-independence.py`.
Follow-up candidate for the CI-architecture epic (#160).

Repair-phase re-derivation at the final lane head `b280f30ce` (the prior
verify passes' evidence was driver-rejected as `worktree_changed`; this pass
re-executed everything at the exact clean head before committing this note).
`uv sync --locked --extra dev` / `uv run ruff check .` /
`uv run ruff format --check .` clean; dedicated pgvector:pg18 container
(127.0.0.1:55499) + `alembic upgrade head` + `maistro-evolve` installed as
the workflow does: targeted `pytest formal/models/test_dangerous_tools.py -q
--hypothesis-seed=0` → **256 passed**; full required-CI equivalent
`pytest formal/models/ -q --timeout=300 --hypothesis-seed=0` → **664
passed** (PG-backed; closes the prior asyncpg/5432 UNVERIFIED finding).
Mutation battery re-executed in a `/tmp` PYTHONPATH-shadowed copy of
`maistro-core/src` (precedence proven via `patterns.__file__` /
`microvm.__file__`; unmutated shadow baseline 256 passed; worktree clean
throughout): 21-of-22 deletion retaining only `sudo\s+` → **193 failed** on
the exact required-CI command; rm-weakening `[/~]`→`/` → **6 failed**;
safe-prefix shadow short-circuit in `is_dangerous_command` → **13 failed**;
deny check removed from `MicroVMSandbox.exec` → **41 failed**.
`tests/test_check_formal_oracle_independence.py` → 3 passed. Gate (real
script): this PR vs base `8bb344e` → bootstrap exit 0 (oracle verified
absent at base via `git cat-file`); scratch clone oracle-only follow-up →
exit 0; scratch clone single-diff oracle+implementation co-change → **exit
1**; unresolvable base → exit 2. ADR-072/ADR-073/SPEC-190 present in-tree;
`formal-conformance` required on develop+main in `branch-protection.json`;
production consumers live (`docker.py:65`, `microvm.py:135`,
`server.py:77,112`); `formal/extractors`/`formal/generated` absent, zero
references outside this notes file. No code change required; residual
org-ruleset/CI-rollup caveats unchanged (above).

Independent verifier pass at the final lane head `d85f39b16` (clean worktree at
the exact SHA; driver check logs covered only uv-sync/ruff/format, so every
number below was re-executed in this pass; all mutations sandboxed under
`/tmp`, worktree untouched): `uv run ruff check .` clean;
`tests/test_check_formal_oracle_independence.py` → **3 passed**; targeted
`pytest formal/models/test_dangerous_tools.py -q --hypothesis-seed=0` →
**256 passed**; full required-CI equivalent `pytest formal/models/ -q
--timeout=300 --hypothesis-seed=0` → **664 passed** against a dedicated
pgvector:pg18 container on 127.0.0.1:55499 after `alembic upgrade head`, with
`maistro-evolve` installed editable as the required workflow does (the
driver's `uv sync` had removed it — see check-0.log). Mutation battery, all
failing the unmutated conformance suite: rm-weakening
`rm\s+-rf\s+[/~]`→`rm\s+-rf\s+/` → **6 failed** (incl. `remove-home`
production-enforcement case — the originally-reported finding is refuted at
this head); 21-of-22 deletion retaining only `sudo\s+` → **193 failed** on the
exact required-CI command; safe-prefix shadow short-circuit in
`is_dangerous_command` (echo/cd/`#` prefixes, patched before microvm import so
enforcement is shadowed too) → **128 failed**; deny check removed from
`MicroVMSandbox.exec` in a PYTHONPATH-shadowed copy (resolution proven via
`microvm.__file__`) → **41 failed**. Oracle-independence gate end-to-end (real
script): worktree vs base `8bb344e` → bootstrap exit 0; scratch clone at this
head: no-change exit 0, oracle-only exit 0, oracle+implementation co-change →
**exit 1**, unresolvable base → **exit 2**. `formal-conformance` confirmed a
required status check for develop and main in `.github/branch-protection.json`;
`formal/extractors`/`formal/generated` absent with zero references outside
this notes file; production consumers live (`docker.py:65`, `microvm.py:135`,
`server.py:77,112`). No closure keywords in the PR body ("Refs #341" only) or
branch commits (sole regex hit is prose "closes the prior finding"). Residuals
unchanged: live GitHub CI rollup for PR 1452 UNVERIFIED (push prohibited); org
rulesets require 0 approvals; gate-script self-neutering co-change remains
visible-in-diff (follow-up #160).

Independent verifier pass at lane head `c83eb9b28` (exact SHA, clean worktree;
`c83eb9b28` differs from `d85f39b16` only by the notes append below, verified
via `git show --stat`). Driver logs (uv sync / ruff / format) re-supplemented
with a full re-execution: `uv run ruff check .` clean; gate unit tests →
**3 passed**; targeted
`pytest formal/models/test_dangerous_tools.py -q --hypothesis-seed=0` →
**256 passed**; full required-CI equivalent `pytest formal/models/ -q
--timeout=300 --hypothesis-seed=0` → **664 passed** against a fresh dedicated
pgvector:pg18 container (127.0.0.1:55495) after `alembic upgrade head`, with
`maistro-evolve`/`formal`/`maistro-core` reinstalled editable as the workflow
does. Mutation battery in an isolated stacked venv (`--system-site-packages`,
resolution proven: `patterns.__file__` inside the sandbox), each reinstall
content-verified before running the unmutated-conformance suite: rm-weakening
`[/~]`→`/` → **6 failed** (remove-home oracle, composition ×3, property,
production enforcement); 21-of-22 deletion retaining only `sudo\s+` →
**193 failed**; benign-prefix allowlist shadow short-circuit in
`is_dangerous_command` → **95 failed**; `MicroVMSandbox.exec` deny check
removed → **41 failed**. Gate end-to-end (real script): worktree vs base
`8bb344e` → bootstrap exit 0 (oracle absent at base via `git cat-file`);
scratch clone at this head: oracle-only committed change → exit 0,
oracle+implementation committed co-change → **exit 1**, unresolvable base →
**exit 2**. `formal-conformance` confirmed required for develop and main
(`branch-protection.json`); `formal/extractors`/`formal/generated` absent, zero
live references; production consumers live (`docker.py:65`, `microvm.py:135`,
`server.py:77,112`); `test_external_content.py` imports no implementation
constants. Live GitHub (read-only refresh at this head): `formal-conformance`
COMPLETED SUCCESS; PR body "Refs #341" only, no closure keywords; overall
rollup still had `integration-scope` IN_PROGRESS → merge-readiness of the
live rollup remains UNVERIFIED (push prohibited); org-ruleset and
gate-script-alone residuals unchanged.

Repair-lane verification at the final lane head `bb4ac576f` (clean worktree at
the exact SHA; job driver check-*.log files were absent from the job
directory, so every number below was executed fresh in this pass; all
mutations sandboxed under `/tmp`, worktree untouched throughout):
`uv run ruff check .` clean, `uv run ruff format --check .` clean (2527
files); `tests/test_check_formal_oracle_independence.py` → **3 passed**;
targeted `pytest formal/models/test_dangerous_tools.py -q
--hypothesis-seed=0` → **256 passed**; full required-CI equivalent
`pytest formal/models/ -q --timeout=300 --hypothesis-seed=0` → **664
passed** against a dedicated pgvector:pg18 container on 127.0.0.1:55477
after `alembic upgrade head`, with `maistro_evolve` importable as the
workflow's explicit install provides. Mutation battery in a
PYTHONPATH-shadowed copy of `maistro-core/src` (precedence proven via
`patterns.__file__`/`microvm.__file__`; unmutated shadow baseline 256
passed), each failing the exact prior-finding command:
`rm\s+-rf\s+[/~]`→`rm\s+-rf\s+/` weakening → **6 failed** (the originally
reported in-memory-weakening finding is refuted at this head);
21-of-22 deletion retaining only `sudo\s+` → **193 failed**; benign-prefix
shadow short-circuit in `is_dangerous_command` → **199 failed**; deny check
removed from `MicroVMSandbox.exec` → **202 failed**; `sudo\s+` narrowing →
**7 failed**. Oracle-independence gate end-to-end (real script, scratch
clone): this PR vs base `8bb344e32b8693574fc0be7a93f86d941616b62c` →
bootstrap **exit 0** (oracle verified absent at base via `git cat-file`);
post-landing oracle-only follow-up → **exit 0**; oracle+implementation
co-change → **exit 1**; unresolvable base → **exit 2** (fails closed).
SECURITY-CONFORMANCE.md claim map re-checked: all 9 referenced test names
resolve to defs in `test_dangerous_tools.py`; ADR-072/ADR-073 and SPEC-190
exist in-tree; `formal/extractors`/`formal/generated` absent with zero
references (retired). Live GitHub (read-only): `formal-conformance`
COMPLETED SUCCESS at PR 1452 head `c83eb9b28`; rulesets re-read — "Pr merge"
(21421373) still `required_approving_review_count: 0`, code-owner review
off, BUT `strict_required_status_checks_policy: true` with
`formal-conformance` required plus a merge queue, so a self-approving
oracle+implementation co-change is mechanically blocked by the required
check regardless of the 0-approval review config; "Main merge" (21701487)
requires 1 approval with the same required checks. Live rollup for PR 1452
additionally shows `test` and `Coverage gate` FAILURE — outside this
issue's formal-conformance scope, unchanged residual for integration
rollup. Residuals unchanged: pushing the local notes-only commits is
prohibited from verification; gate-script self-neutering co-change remains
visible-in-diff (follow-up #160).

Independent review at lane head `981763ca4` (merge of develop `1dea30dfe` into
auto-341; job driver ran `uv sync --locked --extra dev` + `ruff check .` +
`ruff format --check .`, all clean — driver ran no pytest, so every number
below was executed fresh at this SHA; all mutations sandboxed under `/tmp`
via PYTHONPATH plugins, worktree untouched):
targeted `pytest formal/models/test_dangerous_tools.py
formal/models/test_external_content.py -q --hypothesis-seed=0` → **271
passed**; full required-CI equivalent `pytest formal/models/ -q
--hypothesis-seed=0` → **664 passed** against a dedicated pgvector:pg18
container on 127.0.0.1:55931 after `alembic upgrade head` (prior
no-local-Postgres finding resolved; `maistro_evolve` missing from the
driver-synced env was repaired with editable installs mirroring the
workflow's explicit `pip install -e` steps — formal/ declares no
maistro-evolve dependency, so a bare `uv sync` env cannot collect
`test_rsi_*`; env-only, no tree change). In-memory mutation battery
(`pytest_configure` plugin patching `dangerous_tools` + sandbox bindings,
tree untouched): `rm\s+-rf\s+[/~]`→`rm\s+-rf\s+/` weakening → **6 failed**;
21-of-22 deletion retaining only `sudo\s+` → **193 failed**; benign-prefix
allowlist shadow short-circuit (patched into `is_dangerous_command` at
`dangerous_tools`/`microvm`/`docker`/`server` binding sites) → **95 failed** —
all three fail the exact prior-finding command. Gate (real script): base
`1dea30dfe` → bootstrap exit 0 (oracle absent at base); base `HEAD~1`
(notes-only change) → exit 0; unresolvable base → exit 2;
`tests/test_check_formal_oracle_independence.py` → **3 passed** (includes
committed oracle+implementation co-change → violations asserted).
`formal-conformance` required at `.github/branch-protection.json:50,112`;
workflow runs the gate on `pull_request` + `merge_group` and has no
artifact-regeneration step; `formal/extractors`/`formal/generated` absent,
zero references; SECURITY-CONFORMANCE.md claim map names resolve to defs in
`test_dangerous_tools.py`; ADR-072/073 + SPEC-190 exist in-tree. Merge
commit `981763ca4` adds only `security/composition.py` +
`security/warden/detector.py` to the protected prefix (no changes to
`patterns.py`/`dangerous_tools.py`/judged behavior — consistent with the 664
pass). No closure keywords with issue refs in commit bodies `1dea30dfe..HEAD`
or the PR body ("Refs #341" only). Residuals unchanged: live CI rollup for
PR 1452 not observable from this lane (UNVERIFIED, push prohibited);
gate-script self-neutering co-change remains visible-in-diff (follow-up
#160); live ruleset approval counts (0-approval "Pr merge" ruleset) remain a
GitHub-config residual compensated by `strict_required_status_checks_policy`
+ merge queue per prior round's read-only refresh.

Repair-lane pass at the final lane head `2abcf59e9` (clean worktree at the
exact job SHA `2abcf59e9db65e2844aa0fc86e5472057cc2ce9f`; driver check-*.log
files again absent from the job directory, so every number below was executed
fresh at this SHA; mutation edits made in-tree and restored by `cp` from a
/tmp backup, each restore verified with `git diff --quiet` — no git
restore/reset used): all three prior findings adjudicated.
(1) The "in-memory weakening `[/~]`→`/` still passes 65 tests" finding is
STALE at this head: re-executed against
`pytest formal/models/test_dangerous_tools.py -q --hypothesis-seed=0`, the
unmutated baseline is **256 passed** (the file was rewritten since the finding)
and the same source weakening fails it with **6 failed** (remove-home oracle,
property, 3 compositions, production `MicroVMSandbox.exec` enforcement).
(2) The "complete required-CI formal run UNVERIFIED — asyncpg timeout, no
local PostgreSQL" finding is RESOLVED: a dedicated pgvector:pg18 container on
127.0.0.1:5432 + `alembic upgrade head`, then the exact required-CI command
`pytest formal/models/ -q --timeout=300 --hypothesis-seed=0` with
`MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` set → **664 passed**,
`test_run_lease_fence.py` included (the previously-failing command now runs to
completion).
(3) The 0-approval-ruleset finding stands as an org-side residual; the
in-repo mechanical control was re-verified: real
`scripts/check-formal-oracle-independence.py --base 1dea30dfe` → bootstrap
**exit 0** (oracle absent at base), unresolvable base → **exit 2** (fails
closed), `tests/test_check_formal_oracle_independence.py` → **3 passed**
(committed co-change rejection asserted), and the workflow runs the gate on
`pull_request` + `merge_group` with `formal-conformance` required at
`.github/branch-protection.json:50,112`. The demonstrated 21-of-22 deletion
(retaining only `sudo\s+`) was re-run against the exact required-CI command
with the database up → **193 failed**, so the mutation fails required CI.
`uv run ruff check .` and `uv run ruff format --check .` clean;
`formal/extractors`/`formal/generated` still absent with zero live
references. Residuals unchanged: pushing to observe the live rollup for
PR 1452 is prohibited (UNVERIFIED); gate-script self-neutering co-change
remains visible-in-diff (follow-up #160).

Independent verifier pass at the final lane head `6ca739401` (clean worktree at
the exact job SHA; driver check-0/1/2.log = uv sync + ruff check + ruff format,
all clean, no pytest — every number below re-executed fresh in this pass; all
mutations ran through an in-memory `pytest_configure` plugin under `/tmp`
(worktree verified clean via `git status` after the battery)):
`uv run ruff check .` clean; `tests/test_check_formal_oracle_independence.py`
→ **3 passed**; targeted `pytest formal/models/test_dangerous_tools.py -q
--hypothesis-seed=0` → **256 passed**; full required-CI equivalent
`MAISTRO_TEST_PG_DSN/MAISTRO_TEST_DATABASE_URL=… pytest formal/models/ -q
--timeout=300 --hypothesis-seed=0` (PYTHONPATH includes
`packages/maistro-evolve/src`; dedicated pgvector:pg18 on 127.0.0.1:55771
after `alembic upgrade head`) → **664 passed**, `test_run_lease_fence.py`
included. Mutation battery, all failing: rm-weakening `[/~]`→`/` → **6
failed** (prior stale finding refuted again at this head); 21-of-22 deletion
retaining only `sudo\s+` → **193 failed** on the targeted suite AND **193
failed / 471 passed** on the exact full required-CI command with the database
up; benign-prefix shadow short-circuit (patched at `dangerous_tools` and
`microvm` bindings) → **89 failed**; `microvm.is_dangerous_command` → `[]`
(deny check unreachable) → **41 failed**. Gate end-to-end (real script):
this PR vs base `1dea30dfe` → bootstrap **exit 0** (oracle verified absent at
base via `git cat-file`); unresolvable base → **exit 2**; scratch clone:
oracle-only change → **exit 0**; oracle+implementation co-change → **exit 1**.
`formal-conformance` confirmed required at
`.github/branch-protection.json:50,112`; SECURITY-CONFORMANCE.md claim map
names all resolve to defs in `test_dangerous_tools.py` (9/9);
`test_external_content.py` no longer imports `INJECTION`/`INVISIBLE`
implementation constants; `formal/extractors`/`formal/generated` absent with
zero live references. No closure keywords in the PR body ("Refs #341" only) or
commits `1dea30dfe..6ca739401` (sole hit is prose "closes the prior
finding"). Residuals unchanged: live GitHub CI rollup for PR 1452 UNVERIFIED
(push prohibited); org-ruleset 0-approval config and gate-script
self-neutering co-change remain follow-ups for #160.

## Independent pass at head `926d4283a` (driver job 588a1366910a, no check-*.log present)

No driver-provided check logs existed for this pass; every number below was
re-executed fresh in this worktree at the exact starting head. Local env: new
dedicated `pgvector:pg18` container on `127.0.0.1:5432` (same creds as the CI
service) after `alembic upgrade head`, plus `uv pip install -e
packages/maistro-evolve` (CI installs it; local venv did not have it).

- Targeted: `pytest formal/models/test_dangerous_tools.py
  formal/models/test_external_content.py
  tests/test_check_formal_oracle_independence.py -q --hypothesis-seed=0` →
  **274 passed** (256 dangerous-tools + 15 external-content + 3 gate tests).
- Full required-CI equivalent: `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL`
  set to the local CI-shaped DSN, `pytest formal/models/ -q
  --hypothesis-seed=0` → **664 passed in 63s**, `test_run_lease_fence.py`
  included — prior "required-CI formal run UNVERIFIED (no local PG)" finding
  is now resolved with a real PostgreSQL on 127.0.0.1:5432.
- Gate (real script): `--base 60862b6c` (develop base) → **exit 0** bootstrap
  branch, oracle verified absent at base via `git cat-file -e` (exit≠0);
  scratch clone of this head with a committed oracle+patterns co-change →
  **exit 1** with the co-change message. Unresolvable-base exit 2 previously
  demonstrated and unchanged.
- Mutation battery (backup → edit → pytest → restore from backup → `git diff`
  empty after each), all against `test_dangerous_tools.py`:
  weaken `rm\s+-rf\s+[/~]`→`rm\s+-rf\s+/` → **6 failed** (incl.
  `remove-home`, refuting the stale prior finding again); delete 21 of 22
  patterns keeping only `rm\s+-rf\s+[/~]` → **189 failed**; benign-prefix
  shadow short-circuit (`echo|cd|cat|ls ` → `[]`) in
  `is_dangerous_command` → **95 failed**; deny check removed from
  `MicroVMSandbox.exec` → **41 failed**. A malformed-splice intermediate
  state also failed collection — every degrade path is observed, not
  assumed. Suite green again (**256 passed**) after restoration.
- Residuals unchanged: live GitHub rulesets record
  `required_approving_review_count=0` / `require_code_owner_reviews=false`
  (honestly mirrored in `.github/branch-protection.json`), so CODEOWNERS is
  advisory in practice; the operative anti-self-approval mechanism is the
  required `formal-conformance` check failing oracle+implementation
  co-changes (demonstrated exit 1). Gate-script self-neutering co-change and
  live PR-CI rollup remain follow-ups for #160 (push prohibited here).

## Independent pass at head `c932a0d15` (driver job c513cbcb7d01, merge of develop base 60862b6c into auto-341)

Driver checks present and green: `check-0.log` (`uv sync --locked --extra dev`),
`check-1.log` (`ruff check` → All checks passed), `check-2.log` (`ruff format
--check` → 2533 files already formatted). Everything below re-executed fresh at
this exact head; no tree edits were made (mutations ran via in-memory pytest
plugins on `PYTHONPATH=/tmp/maistro-muts`, so the worktree stayed pristine).

- Targeted: `pytest formal/models/test_dangerous_tools.py
  formal/models/test_external_content.py -q --hypothesis-seed=0` → **271
  passed**; `pytest tests/test_check_formal_oracle_independence.py -q` → **3
  passed**. `uv run ruff check .` re-run independently → clean.
- Full required-CI equivalent: dedicated `pgvector:pg18` container on
  `127.0.0.1:5432` (CI-shaped creds), `alembic upgrade head`,
  `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` set, `pytest formal/models/
  -q --timeout=300 --hypothesis-seed=0` → **664 passed in 43.67s** (after `uv
  pip install -e packages/maistro-evolve`, which CI installs and local venv
  lacked).
- Gate (real script): `--base 60862b6c` → **exit 0** (bootstrap: oracle absent
  at base); `--base not-a-commit` → **exit 2** (fails closed); scratch clone of
  this head with a committed oracle+`patterns.py` co-change → **exit 1**.
- Mutation battery (in-memory, this head): weaken `rm\s+-rf\s+[/~]` →
  `rm\s+-rf\s+/` → **6 failed** (remove-home witnesses — stale prior finding
  again refuted); delete 21 of 22 keeping only `sudo\s+` → **193 failed**;
  benign-prefix shadow short-circuit → **95 failed**; deny check dropped from
  `MicroVMSandbox.exec` → **41 failed** (exactly the enforcement-path tests).
- Live read-only refresh (`gh pr view 1452`): head `headRefOid` equals
  `c932a0d15…`, draft, body "Refs #341" (no fixes/closes/resolves), and the
  **`formal-conformance` check is SUCCESS on this exact head** (run
  36063055491); `.github/branch-protection.json` lists `formal-conformance` as
  required on both develop and main. Unrelated rollup noise at this snapshot:
  `integration-scope`/`gates-ran`/MinIO jobs failing, `test`/`docker-build`
  in progress — none touch this change's 16-file surface; PR remains a draft
  claim-stake.

Repair-lane validation at head `e5b013697` (this lane's final SHA; driver
check logs covered only uv-sync/ruff/format, so every number below was
executed fresh in this pass; worktree unmodified except this note — mutations
ran via in-memory pytest plugins on `PYTHONPATH=/tmp/mutations`).

- `uv run ruff check .` clean; `uv run ruff format --check .` → 2533 files
  already formatted.
- Targeted: `pytest formal/models/test_dangerous_tools.py -q
  --hypothesis-seed=0` → **256 passed**; `pytest
  tests/test_check_formal_oracle_independence.py formal/models/test_external_content.py -q`
  → **18 passed**.
- Full required-CI equivalent: dedicated `pgvector:pg18` container on
  `127.0.0.1:5432` (CI-shaped creds), `alembic upgrade head`, both DSN env
  vars set, `pytest formal/models/ -q --hypothesis-seed=0` → **664 passed in
  58.35s**.
- 21-of-22 deletion under the **exact full required command** (same PG setup,
  in-memory plugin keeping only `sudo\s+`) → **193 failed, 471 passed** —
  the demonstrated mutation fails required CI, not just the targeted file.
- Mutation battery (targeted file, this head): weaken `rm\s+-rf\s+[/~]` →
  `rm\s+-rf\s+/` → **6 failed**; delete-21 → **193 failed**; benign-prefix
  shadow → **95 failed**; deny check dropped (plugin patched both
  `microvm.is_dangerous_command` and the direct predicate, stricter than the
  prior 41-failure seam-only variant) → **206 failed**. All four fail.
- Gate (real script): `--base 60862b6c` → **exit 0** (bootstrap: oracle
  absent at base); unresolvable base → **exit 2** (fails closed); scratch
  worktree co-change vs `e5b013697` (oracle already governed at base) →
  **exit 1**; oracle-only change → **exit 0**. The bootstrap exception only
  applies when the oracle is absent at the base, so post-landing co-changes
  are rejected.
- `formal/extractors`/`formal/generated` absent from the tree; grep finds
  zero live references (only inventory-note history). ADR-072, ADR-073,
  SPEC-190 all exist under `docs/`; `formal/SECURITY-CONFORMANCE.md` maps 6
  claims to named tests that all resolve to defs in `test_dangerous_tools.py`.
- Production reachability: `microvm.py:22,135` (deny check in `exec`),
  `opencode.py:112` (production `MicroVMSandbox` construction);
  `formal-conformance` remains a required status check on develop+main
  (`branch-protection.json:50,112`).

## Independent verifier pass — d9ece4b04 (2025-09-24)

Re-derived from the issue text at head `d9ece4b04f527c6f3547cf39a85285c9a8944c50`; all
commands executed fresh in the lane worktree (tree untouched except this note).

- Targeted: `pytest formal/models/test_dangerous_tools.py
  formal/models/test_external_content.py tests/test_check_formal_oracle_independence.py
  -q --hypothesis-seed=0` → **274 passed**.
- Full required-CI equivalent: no local 5432; reused healthy shared `pgvector:pg18`
  instance (`maistro-postgres`, `127.0.0.1:5433`) with a dedicated throwaway database
  (`maistro_formal_341v`), fresh `alembic upgrade head`, installed `-e
  packages/maistro-evolve` (the driver `uv sync` had uninstalled it; CI installs it
  explicitly), both DSN env vars set, `pytest formal/models/ -q --timeout=300
  --hypothesis-seed=0` → **664 passed in 58.28s**.
- Demonstrated 21-of-22 deletion (in-memory plugin keeping only `sudo\s+`) under the
  exact full required command with PG → **193 failed, 471 passed**.
- Mutation battery (targeted file, seam-precise plugins in /tmp, no tree edits):
  weaken `rm\s+-rf\s+[/~]` → `rm\s+-rf\s+/` → **6 failed**; benign-prefix shadow
  (predicate + executor binding) → **95 failed**; executor deny-check dropped only
  (`microvm.is_dangerous_command = λ: []`, predicate left intact — the precise
  "unreachable from production" mutation) → **41 failed**. All four classes fail.
- Gate (real script, true exit codes): `--base 60862b6c` → **exit 0** (bootstrap);
  unresolvable base → **exit 2**; isolated /tmp mini-repo with a copy of the script:
  oracle+`packages/maistro-core/src/maistro/security/` co-change → **exit 1**;
  oracle-only → **exit 0**. First harness attempt used a non-protected impl path and
  was discarded; recorded numbers above are from the corrected protected-path fixture.
- `uv run ruff check .` → clean. Live PR #1452 body/head refreshed read-only: only
  `Refs #341`, no closure keywords; zero closure keywords in any commit body on the
  branch. Required contexts confirmed at `.github/branch-protection.json:50,112`.
- Residuals: live CI status on this exact head not independently observed (draft PR;
  push prohibited) — local full required-command run at this head is the operative
  evidence; org rulesets still require 0 approvals (prior finding, org-side).
