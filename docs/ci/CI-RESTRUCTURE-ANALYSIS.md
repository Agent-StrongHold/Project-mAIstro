# CI restructuring analysis and design

## Baseline (origin/develop `f93888f0`)

The request described a 29-step Quality job. The checked-out baseline actually
contains 37 steps in `quality-gate`: 7 shared setup steps, 30 check/dependency
steps, including the Vulture ledger. Vulture is also the canonical required
check in `vulture-ratchet.yml`, so this change keeps that check once in the
repository-wide workflow and removes the duplicate Quality invocation. The
result is 28 independently reportable Quality checks plus one PostgreSQL job
that groups migration setup with its dependent acceptance-state check.

The baseline has three SAST tools in one 9-step job and 13 multi-step CI jobs.
The service-coupled CI jobs are deliberately not split into fake independent
checks: their ordering and shared database, MinIO, Docker daemon, or Compose
lifecycle is part of what they validate.

## Quality baseline: every step and disposition

| # | Baseline step | Validation / dependency | Estimate |
| ---: | --- | --- | ---: |
| 1 | checkout (full history) | source and ratchet base | 0.2m |
| 2 | Install uv | pinned package runner | 0.2m |
| 3 | Setup Python 3.12 | interpreter | 0.2m |
| 4 | uv sync (all extras) | locked dev environment; shared by every check | 0.5–2m |
| 5 | install maistro-evolve | formal/ import dependency | 0.1m |
| 6 | install age + age-keygen | acceptance/vault test dependency | 0.5–4m |
| 7 | install quality tools | radon/xenon/vulture/pyright/interrogate | 0.2m |
| 8 | ruff lint | full lint ruleset | 0.5–1m |
| 9 | ruff format check | formatting | 0.2–0.5m |
| 10 | radon CC ratchet | new/regressed complexity | 0.3–1m |
| 11 | radon CC report | complexity report | 0.2–0.5m |
| 12 | version consistency | VERSION and all version sites | 0.2m |
| 13 | release consistency | VERSION/CHANGELOG/README/tags | 0.2m |
| 14 | doc links | relative Markdown links | 0.2m |
| 15 | enumeration coverage | derived security/control lists | 0.2m |
| 16 | IFEval provenance | vendored grader/corpus hashes | 0.2m |
| 17 | BFCL provenance | vendored checker/corpus hashes | 0.2m |
| 18 | xenon ratchet | complexity regression against 77 baseline | 0.5–1m |
| 19 | vulture ledger | exact dead-code identities; now owned by Vulture Ratchet | 0.5–2m |
| 20 | reachability ratchet | unwired modules | 0.3–1m |
| 21 | wiring reads ratchet | DI attributes read back | 0.2–0.5m; base required |
| 22 | agent store write path | one writer for `stores.agents` | 0.2m |
| 23 | contract marker ledger | ADR-032 marker cross-check | 0.2m |
| 24 | convergence matrix | subsystem ownership census | 0.2m |
| 25 | reachability dispositions | owner/disposition for unreachable modules | 0.2m |
| 26 | security inventory | SECURITY.md claims | 0.2m |
| 27 | image inventory | Dockerfile disposition | 0.2m |
| 28 | backlog consistency | legend/usage/citations | 0.2m |
| 29 | Apply migrations | prerequisite for acceptance tests; shares PostgreSQL | 0.5–2m |
| 30 | acceptance-state ratchet + mandate | AC tests, ratchet and PR mandate; depends on 29 | 2–8m |
| 31 | mypy --strict | core type gate | 1–3m |
| 32 | pyright ratchet | cross-check against 21 baseline | 1–3m |
| 33 | Hypothesis property tests | formal property suite | 1–5m |
| 34 | execution lifecycles | one lifecycle-spine classification | 0.2m |
| 35 | model egress | direct caller ratchet | 0.2m |
| 36 | Architecture fitness functions | execution architecture tests | 1–3m |
| 37 | interrogate | docstring floors | 0.3–1m |

Coverage remains four jobs because producers and the aggregate gate are
artifact- and service-dependent: `coverage-unit` (no service, 8 steps),
`coverage-archive` (MinIO, 7), `coverage-postgres` (PostgreSQL, 7), and
`coverage-gate` (artifact combine/diff gate, 7). Splitting those steps would
change the measured data or lose the service/artifact dependency.

## SAST baseline: every step and disposition

| # | Baseline step | Validation / dependency | Estimate |
| ---: | --- | --- | ---: |
| 1 | checkout, full history | source and gitleaks history | 0.2m |
| 2 | Install uv + Python | setup wrapper | 0.2m |
| 3 | Setup Python 3.12 | interpreter | 0.2m |
| 4 | uv sync | locked environment for bandit | 0.5–2m |
| 5 | install SAST tools (`bandit`) | bandit CLI | 0.1m |
| 6 | bandit | zero Medium+ in owned source | 0.5–2m |
| 7 | semgrep | custom + security/OWASP/secrets rules | 1–5m |
| 8 | install gitleaks CLI | pinned, checksum-verified binary | 0.2–1m |
| 9 | gitleaks | changed range or full protected history | 0.2–2m |

The three tool checks are now separate reusable-workflow callers. Bandit and
Semgrep retain the Python environment; Gitleaks retains full checkout history
but does not pay for an unused uv sync.

## Other CI monolithic jobs inspected

These jobs were read in full and retain their grouping because the listed steps
share a required service or an intentional process boundary:

| Job | Steps (in order) | Shared dependency / estimate |
| --- | --- | --- |
| `lint-and-type-check` | checkout; Python; setup-uv; sync; monorepo layout; merge markers; cross-package imports; frontend routes; deployment claims; secret labels; retired guidance; compose secrets; promotion surface; connection credentials; owned-store access; public routes; shell execution; build context | one static environment; 3–8m |
| `postgres` | checkout; Python; setup-uv; sync; migration-chain test; upgrade; downgrade/upgrade; persistence; container wiring; workspace conformance | pg17/18 matrix and migration ordering; 5–15m |
| `object-storage` | checkout; Python; setup-uv; sync; start MinIO; archive conformance | one MinIO daemon; 3–8m |
| `test` | checkout; Python; setup-uv; age/bubblewrap; sync; bootstrap/core/server/canvas/turing/backend/design/root/RSI+evolve suites; Node; frontend lint/build/test/audit; backend requirements/tests; same-process leakage test; inventory | deliberate per-tree process isolation plus final same-process test; 10–25m |
| `durable-events` | checkout; Python; setup-uv; sync; event conformance; schema-agreement test | one PostgreSQL service; 3–8m |
| `strike-ladder` | checkout; Python; setup-uv; sync; strike conformance | one PostgreSQL service; 2–6m |
| `hive-conductor-e2e-ui` | checkout; base-image prepull; Compose Playwright run; diagnostics; teardown | one Compose lifecycle; 8–20m |
| `hive-conductor-e2e` | checkout; base-image prepull; Compose API run; logs; teardown | one Compose lifecycle; 8–20m |
| `wheel-imports` | checkout; Python; setup-uv; build every wheel; clean-venv imports | build artifacts feed import test; 3–10m |
| `docker-build` | checkout; Buildx; runtime auth; prepull; engine build/smoke; hive build; canary BuildKit/classic test; tag; research build; RSI build | shared builder/cache, local images, and canary files; 12–25m |
| `workflow-lint` | checkout; merge-group scope; install actionlint/shellcheck; actionlint; tools shellcheck; Python; PyYAML; required-check contract; uv setup contract; write safety; branch protection | all checks inspect one workflow tree; 2–6m |

`ci.security` was an exact duplicate of the pip-audit check already in
`security.yml` (same freeze/audit/gate, differing only in the less-complete
`--extra dev` setup). It was removed; `security.yml`'s all-extras
`Supply chain (pip-audit)` is now the sole owner. The `ruff check .` and
`ruff format --check .` invocations were likewise removed from CI's static job;
Quality owns those exact invocations. The commands still run on every PR.

## Reusable workflows and deduplication

* `reusable-quality-check.yml` owns checkout, Python, uv, locked environment,
  evolve, analyzer installation, and one supplied quality command.
* `reusable-quality-postgres-check.yml` owns the pgvector service and the
  migration/acceptance environment. Migration and its dependent AC check stay
  together because a service container is job-scoped.
* `reusable-sast-check.yml` owns the common SAST checkout and optional Python
  setup, with the original install and scan commands supplied by each caller.

| Check | Was duplicated in | Now in |
| --- | --- | --- |
| `ruff check .` | `quality.yml`, `ci.yml` lint-and-type-check | `quality.yml` via reusable quality caller |
| `ruff format --check .` | `quality.yml`, `ci.yml` lint-and-type-check | `quality.yml` via reusable quality caller |
| pip-audit freeze/audit/gate | `ci.yml` security, `security.yml` supply-chain | `security.yml` supply-chain only |
| Vulture exact ledger invocation | `quality.yml`, `vulture-ratchet.yml` | `vulture-ratchet.yml` exact-debt-ledger only |

No tool, argument, baseline, service, or pass/fail criterion was weakened;
only the owner/check boundary changed.
