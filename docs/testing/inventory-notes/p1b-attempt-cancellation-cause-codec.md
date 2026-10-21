---
inventory-delta:
  packages/maistro-core/tests: +36
---
# p1b-attempt-cancellation-cause-codec

Adds 36 pure codec/model cases for #1885 on base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`: unknown/requested/recovered causes,
seven canonical transport shapes, nested DurableRunRecord lineage, independent
legacy payloads, non-finite evidence, include/exclude selection, and invalid-input
rejection. Reconciles preserved test work from
`ec986e1820ed9077d99fddd5d9a7a8290bc90d03`; obsolete pre-#1884 dependency skips
are removed now that the model contract has landed. No existing tests removed.

Core collection: expected 16,360 before this change, collected 16,396; scoped
inventory check passes with this +36 note, zero duplicate test identities/files.
Focused codec plus model suite: 70 passed, no skips. Ruff and formatting pass.
Adjacent spine/fencing/recovery suite: 305 passed, 138 PostgreSQL-dependent
cases skipped because no test DSN was configured. These skips prove no durable
backend behavior.

In a separate disposable archive, all six minimal mutants were detected by
actual assertion failures (not collection errors): drop typed cause, emit null
cause, drop all null fields, encode non-finite evidence as null, bypass child
null-omission serialization, and bypass model validation. The repair worktree's
production files were never mutated.

Full-core regression with the additions staged and explicit trusted base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`: 15,326 passed, 1,067 skipped,
3 xfailed, 52 warnings. The initial unstaged run had one provenance failure:
the self-reference guard correctly refused HEAD as its own base while the
additions were still untracked. Staging the actual candidate changes resolved
that setup failure without altering any gate. Skips, expected failures and
warnings remain limitations; this does not claim full CI or merge readiness.

This leaf changes only tests and this inventory note. Typed fixtures do not
activate cancellation writers, grant recovery authority, alter defaults, or prove
PostgreSQL/SQLite/archive persistence. #232/#1151 remain separate parent work.
