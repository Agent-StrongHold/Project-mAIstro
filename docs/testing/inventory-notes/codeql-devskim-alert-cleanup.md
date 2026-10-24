---
inventory-delta:
  tests/: +9
  packages/hive-conductor/backend/tests: +10
  packages/maistro-bootstrap/tests: +2
  packages/maistro-design/tests: +2
---
# CodeQL + DevSkim open-alert cleanup

Repair for the accumulated GitHub code-scanning backlog on `develop`
(~626 open alerts: ~22 CodeQL + ~604 DevSkim). Path-injection test deltas
live in the sibling note `fix-codeql-path-injection-ace4.md`.

## DevSkim

### Scope: drop pure-data / non-shipped trees from the scan

`ignore-globs` in `.github/workflows/devskim.yml` gains location-based
exclusions (same contract as existing entries — directories that hold no
shipped executable surface, never a filename shape):

| Glob | Why |
| --- | --- |
| `**/maistro_design/systems/catalog/**` | Bundled Open Design fixtures (json/md/css only). DS173237 treated every git commit sha in `catalog.json` as a hard-coded token (~150 alerts). |
| `**/benchmarks/corpora/**` | Generated benchmark admission JSON (commit shas + patch metadata). Same DS173237 noise (~150 alerts). |
| `formal/**` | Hypothesis conformance suite — already excluded from CodeQL; fixtures deliberately exercise eval/http shapes. |
| `.github/**` | Actions workflows / Dependabot — CI loopback healthchecks and DEBUG toggles, not product surface. |
| `deploy/**` | Ops scripts, not installed library/app code. |
| `alembic/**` | Migration env, not shipped runtime. |

`tests/test_devskim_scan_scope.py` pins the six noisy trees (+6 parametrized
cases) in `test_the_noisy_trees_are_still_excluded`; the suite delta is
+7 because the companion CodeQL commit also added one mutation-baseline case.

### Error-severity false positives cleared in place

| Rule | Remedy |
| --- | --- |
| DS173237 on `scripts/vendor_{bfcl,ifeval}.py`, `bfcl_real.py`, `ifeval_real.py`, `repo_history.py`, `release.yml` `*_SHA256` pins | Same-line dated suppressions — integrity digests, not credentials. |
| DS148264 on tournament `random.shuffle` / sim `random.Random(seed)` | Same-line dated suppressions — non-cryptographic use. |
| DS440010 on `DESIGN_OUTPUT_SHAPE_ERROR` | Same-line dated suppression — rule matches the substring `SHA` inside `SHAPE`. |
| DS126858 on `FakeEmbeddingClient` | Eliminated: switched the test stand-in from `md5` to `sha256`. |

## CodeQL

| Rule | Fix |
| --- | --- |
| `py/path-injection` | `realpath` + `startswith(root+sep)` in RSI policy, workspace mounts, Lulu preflight, promotion patch export |
| `py/stack-trace-exposure` | Kind-only public text on /health optional-router outcomes (plus prior develop sanitization on DAG/evolution/RSI/canvas) |
| `py/regex-injection` | `re.escape` before compile in design consistency markers (`_marker_re`) |
| `py/clear-text-logging-sensitive-data` | Rename credential rotation log event; annotate mutation-baseline CI prints |
| `js/prototype-pollution-utility` | Explicit per-segment prototype-key refusal in `BookWorkspace` path walker |

Vendored `**/third_party/**` ReDoS alerts stay paths-ignored and should
auto-close on the next CodeQL analysis upload.
