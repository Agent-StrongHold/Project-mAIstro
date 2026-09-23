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
