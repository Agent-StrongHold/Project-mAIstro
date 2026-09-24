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
