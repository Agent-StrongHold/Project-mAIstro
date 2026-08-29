---
inventory-delta:
  tests/: +29
---
# claude-m2-432-connection-credentials-faf9

All twenty-nine are `tests/test_check_connection_credentials.py`. Nothing was
removed or renamed, so the delta is the whole of the change. They fall into two
groups, and the second is there for a reason worth recording.

**Twenty-one cover the new gate**, `scripts/check-connection-credentials.py`
(#432), and the split is deliberately lopsided toward what it must **not**
report: six cover the shapes the issue was filed for (an `os.environ.get`
fallback, `os.getenv`, a `default=` keyword, a `*_URL`-named assignment, its
annotated form, and an `alembic.ini` `sqlalchemy.url` key), and ten cover text
that merely contains a credential-bearing URL — docstrings, comments, the error
message `maistro.config.database` raises, a `URLLIB_*` name whose tail is not
`URL`, interpolated ini values, and a path that looks like userinfo.

That ratio is the point. This repository has dozens of legitimate
`user:pass@host` strings in redaction tests and format documentation; a gate
that flagged them would be routed around rather than fixed, so false positives
are the failure mode worth spending tests on. The remaining five run the gate
as CI does, exercise both exit paths, and check that an unparseable or
undecodable file is skipped rather than crashing it.

**Eight cover `packages/maistro-canvas/frontend/server/config.py`**, the module
that replaced the two literals. It lives outside every `MEASURED_ROOTS` entry
and outside the mypy set, and that package's Python tests are not run by any
workflow — so tested from `tests/` or not at all. Left untested it would occupy
exactly the position the code it replaced occupied: a database credential seam
nothing in CI executes. They pin that `DATABASE_URL` wins outright, that
`POSTGRES_PASSWORD` composes the Compose profile's URL, that whitespace counts
as unset, that an unconfigured database raises naming both settings, and that
no `mcp:mcp` default survives anywhere in the result.
