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
