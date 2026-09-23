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
