# Code quality gates

This document states what the repository actually enforces. A rule described here as blocking must have a workflow, type invariant, or test behind it; known gaps are named rather than implied away.

The blocking workflows are primarily [`.github/workflows/quality.yml`](../.github/workflows/quality.yml), [`ci.yml`](../.github/workflows/ci.yml), the registry workflow, and the dedicated security/mutation workflows.

## Ratchets and floors

A **floor** is a fixed minimum/maximum threshold. A **ratchet** records reviewed current debt and forbids silent regression. Identity ratchets are preferred where a count could hide a same-count substitution. Count ratchets remain where the measured object is inherently aggregate, but they do not hold spare slack: an unbanked improvement fails until the reviewed baseline is lowered too.

## Current blocking gates

| Gate | Shape | Authority | What it stops |
|---|---|---|---|
| `ruff check` (full ruleset) | floor | zero findings | lint violations |
| `ruff format --check` | floor | zero diffs | unformatted code |
| `mypy --strict` | floor | zero errors, all nine `packages/*/src` | type errors |
| pyright | ratchet | 24 | type errors mypy does not catch |
| radon CC | identity ratchet | `quality/radon-baseline.json` | a new or regressed complexity hotspot |
| xenon | count ratchet | 77 | per-function > B, per-module > B, project average > A |
| vulture | identity ratchet | `quality/vulture-baseline.json`, in `quality.yml` + `vulture-ratchet.yml` | any change to the reviewed finding set, by name — a new finding, a fixed one left unbanked, or a same-count substitution |
| reachability | identity ratchet | `quality/reachability-baseline.json` | a module built but never wired to any entry point |
| convergence matrix | identity ratchet | `docs/architecture/CONVERGENCE-MATRIX.md` | a subsystem left unclassified, or a row whose ownership/reachability claim no longer matches the code |
| reachability dispositions | identity ratchet | `quality/reachability-dispositions.json` | an unreachable module with no disposition, a disposition left behind after its module became reachable, or a CONNECT/RETIRE row with no named root/replacement |
| backlog consistency | floor | `BACKLOG.md` legends | an item using a status or gap marker no legend defines, a duplicate id, an undocumented id prefix, or a citation to an ADR/spec that does not exist |
| coverage (aggregate) | floor | 86% line + branch, publish set | the repository as a whole rotting |
| coverage (diff) | floor | per file: 90% lines, 80% branch arcs, on lines the PR touched | a single undertested change the aggregate cannot see |
| interrogate | ratchet | 38 / 45 / 63 / 46 per tree | missing docstrings, per-subtree floors |
| suite inventory | identity ratchet | `docs/testing/inventory/baseline.json` + per-change deltas in `inventory-notes/` | a suite silently ceasing to collect |
| enumeration coverage | identity ratchet | `scripts/check_enumerations.py` | a derived control list drifting from its source enum |
| doc links | floor | zero broken | a relative markdown link whose target does not exist |
| version consistency | floor | exact match | any version site disagreeing with `VERSION` |
| benchmark provenance | floor | pinned digests | a vendored IFEval/BFCL grader or corpus changing unnoticed |
| architecture fitness | floor | zero violations | a forbidden cross-layer dependency |
| execution lifecycles | identity ratchet | `quality/execution-lifecycles.json` | a new work-state enum nobody classified, or an entry left behind after its enum was deleted |
| model egress | identity ratchet | `quality/model-egress.json` | a new module calling a model endpoint directly, or an entry left behind after one was migrated |

The blocking Vulture workflow pins Vulture 2.16 and scans `packages/*/src` at confidence 60 while excluding `*/third_party/*`; `quality/vulture-baseline.json` is banked from that exact command so a different analyzer version or scan scope cannot silently redefine the reviewed identity set.

The convergence-matrix checker is intentionally **structural**. It does not prove that prose such as “this product route traverses Warden” is operationally true. The matrix now says that limitation explicitly. Product-path claims require acceptance evidence or human re-audit; a green matrix check alone is not evidence of runtime enforcement.

## #36 architecture-fitness invariants

All six minimum invariants now have an enforceable owner. Two are construction-time type invariants rather than duplicate CI scanners.

| Invariant | Enforced by |
|---|---|
| 1. No new universal execution lifecycle outside Run/NodeRun/Attempt | `scripts/check-execution-lifecycles.py` + identity ledger |
| 2. No new direct model/tool/effect-provider bypass | `scripts/check-model-egress.py` freezes the current direct caller set while #56 converges the boundary |
| 3. No second durable Workspace/Event-sequence authority | `EventEnvelope`/event-store construction rules refuse conflicting scope/sequence authority; event tests pin it |
| 4. No unscoped durable project-owned execution objects | `Run`/`NodeRun` require Project scope and Run rejects a mismatched Graph snapshot |
| 5. No outward core dependency-direction violations | `packages/maistro-core/tests/fitness/test_import_boundaries.py` |
| 6. Compatibility owners cannot silently present as canonical | the same blocking fitness suite AST-scans direct public type aliases against a reviewed identity ledger and requires each reviewed alias to be explicitly described as compatibility-only in its source; new/stale/unbannered aliases fail |

Invariants 3 and 4 are stronger at construction than a later grep: the invalid object cannot be created. Invariant 6 is different — an alias can always be written — so it is now mechanically checked rather than left as convention.

## Coverage: aggregate and diff answer different questions

Aggregate coverage protects the repository as a whole. The current publish-set floor is **87%**, raised after the Canvas namespace blind spot was corrected under #171.

Diff coverage scores changed lines/branch arcs **per file**, not pooled across the PR. Its current floors are 90% lines / 80% branch arcs.

Coverage scope matters: a file absent from every coverage producer is invisible to the diff checker. The combined report now includes the publish set, `maistro-server`, and the PostgreSQL producer added after #211. The remaining named non-publish scope gap (`maistro-turing`, `maistro-design`, `hive-conductor`) is tracked by #163; a green diff gate must not be read as proof those trees were scored until that issue lands.

`include_namespace_packages = true` remains load-bearing for namespace-package trees such as Canvas.

## Acceptance-state ratchet and per-PR mandate

`scripts/check-ac-state.py` measures acceptance evidence at the criterion level:

1. `declared` — criterion exists with an ID;
2. `covered` — a test claims the criterion;
3. `passing` — that test passes;
4. `reachable` — the module the criterion asserts about is reachable from a real entry point.

A document tier is the highest rung **all** of its criteria have reached. A passing unit test therefore cannot by itself prove a product-path claim.

Two enforcement modes operate over the same corpus:

- `--ratchet` holds reviewed legacy evidence debt in a bound folded from `quality/ac-state-notes/` at the base revision (#585, ADR-082926-25a2): debt counters fold by minimum, `design_coverage` by maximum, and a branch writes only its own note so two branches never conflict. The M0 closeout reconciled every current contradicted/unverifiable completion claim, so both completion-claim counters are now zero; remaining AC-ID/spec evidence retrofit debt stays explicit and non-growing.
- `--mandate <base>` is zero-tolerance for criteria a PR creates or newly claims. A new criterion must be evidenced or carry a visible per-criterion unproven marker with a reason.

Example explicit deferral:

```markdown
<!-- ac-state: unproven AC-3 - blocked on the durable store (#132) -->
```

The mandate cannot be banked away. Legacy retrofit debt stays grandfathered to the ratchet; new claims do not become legacy merely because a PR wants to merge.

## ADR lifecycle evidence

ADR-097 defines `Proposed` as under discussion and `Accepted` as a decision made. From the M0 closeout boundary (2026-08-24), `maistro-registry` prospectively requires newly-authored records to carry dated lifecycle history whose latest entry matches front matter; taken decisions require their acceptance metadata/owner evidence. Legacy/backfilled records remain readable and continue through the acceptance-state debt process rather than being bulk-rewritten by a schema change. See #239.

The `/adr` and `/spec` scaffolds emit lifecycle history immediately. When a record advances, contributors append the dated transition and update the corresponding lifecycle metadata rather than editing `status` alone.

## Design coverage

Design coverage is decision-weighted: for each taken ADR (`Accepted`, `Fully Specced`, or `Implemented`), measure the fraction of its own and implementing specs' criteria that reach `reachable`, then average one vote per decision. A taken decision with no evidence contributes zero rather than disappearing from the denominator. The generator uses this same ADR-only taken-state set; SPEC-only states such as `In Progress` and `Tests Passing` are not decision states.

The **current reviewed floor is always the fold over `quality/ac-state-notes/`**, not a number copied into prose; the gate prints it on every verdict, and `--show-bounds` prints it on demand. Accepting a real new decision can legitimately lower the percentage because new work becomes owed; such a denominator change must be banked and explained. Proving criteria raises it and the higher value must likewise be banked so the gain cannot pay for a later regression.

## Other dedicated gates

Security scanning (Bandit, Semgrep, gitleaks), dependency audit, container/SBOM/signing checks, and mutation testing live in their dedicated workflows. `SECURITY.md` has its own inventory consistency gate under #157; a green security-document check is limited to the claims that checker can mechanically verify.

## Running the architecture/governance gates locally

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/maistro-core/src
uv run python scripts/check-radon-baseline.py
uv run python scripts/check-reachability.py
uv run python scripts/check-convergence-matrix.py
uv run python scripts/check-reachability-dispositions.py
uv run python scripts/check-backlog-consistency.py
uv run python scripts/check-execution-lifecycles.py
uv run python scripts/check-model-egress.py
uv run pytest packages/maistro-core/tests/fitness -v --timeout=30
uv run python scripts/check-suite-inventory.py
uv run python scripts/check-doc-links.py
uv run python scripts/bump_version.py --check
uv run python scripts/check-vulture-baseline.py packages/*/src \
  --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-ac-state.py --run-tests --ratchet
```

Banking is an explicit reviewed operation. Do not hand-edit a baseline merely to make a failing gate match a new defect.