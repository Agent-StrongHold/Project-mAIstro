# Repository Standards Index

Load this index when a task depends on repository mechanics or artifact conventions rather than product architecture.

Current canonical sources are being normalized in PR #1656. Until that reconciliation is complete, use these existing sources deliberately rather than preloading them:

- `AGENTS.md`: package placement, build/test commands, PR conventions, secrets, generated-file boundaries.
- `docs/WAYS-OF-WORKING.md`: development workflow and collaboration conventions; subject to reconciliation against the new pre-1.0 standards.
- `docs/testing/` and `docs/EXPLORATORY-TESTING.md`: testing practices.
- `docs/ci/` and `docs/quality-gates.md`: current CI behavior; descriptive evidence, not automatically authoritative policy while the CI audit is pending.

When an existing convention conflicts with the pre-1.0 development or authority standards, surface the conflict rather than preserving the older convention for compatibility.
