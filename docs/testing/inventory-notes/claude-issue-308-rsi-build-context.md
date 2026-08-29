---
inventory-delta:
  tests/: +27
---
# claude-issue-308-rsi-build-context

All twenty-seven are new, in `tests/test_check_build_context.py`, the suite for
the build-context gate. Nothing removed or renamed.

The gate reads two `.dockerignore` files and a Dockerfile, so its tests are
about the three ways a secret could still reach an image: a rule present in one
ignore file and not the other (BuildKit reads one, the classic builder the
other, so a rule in only one file is a protection that depends on which ran), a
bare `COPY .` returning, and any of the nine `MUST_DENY` patterns going missing
— one parametrised case per pattern, so dropping any single one fails.

The fourth class is the one worth naming: a rule so broad it strips **source**.
`**/data/` is the natural rule to reach for and would remove the Conductor's
shipped dashboards and the BFCL corpus from every image; `**/vault/` would
remove `packages/maistro-core/tests/vault/`. The gate caught the second of
those in this change's own first draft, which is why the case is in the suite
rather than only in the comment.

A gate people have to disable to get a working image is a gate that gets
disabled, so "denies nothing tracked" is as load-bearing here as "denies every
secret".
