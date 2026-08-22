# Code quality gates

What actually runs, and what each gate will and will not stop. Every entry here
is a step in [`.github/workflows/quality.yml`](../.github/workflows/quality.yml)
or [`ci.yml`](../.github/workflows/ci.yml) — if a rule is not in this file, it is
not enforced, and a rule that is enforced is enforced on every pull request
against `main`, `integration`, and `develop`.

This replaces the June-2026 audit documents (`quality-standards.md`,
`claude-quality-enforcement.md`, and the three dated `code-quality-*` scans).
Those were point-in-time findings, not standards: every specific defect they
named has since been fixed, and they described the pre-monorepo `src/maistro/`
layout. Their durable content is the gates below, which run rather than
describe. Provenance remains in git history.

## Ratchets vs. floors

Two different shapes, and the difference matters when you are deciding whether
a change is allowed to make a number worse.

A **ratchet** records the currently-tolerated set in a checked-in baseline and
fails on anything worse than it. It never auto-grows: widening a baseline is an
edit a reviewer sees. The backlog is worked down over time rather than in one
pull request.

A **floor** is a fixed threshold with no baseline. It does not move with the
code.

A ratchet keyed on a *count* has a known weakness: one fix pays for one new
defect, so the total can stand still while the code churns. Where that matters,
the gate is keyed on *identity* instead — the exact finding, not how many there
are — and then a defect that gets fixed but left in the baseline fails the build
too. That asymmetry is deliberate: retained slack could otherwise pay for a
later regression.

## The gates

| Gate | Shape | Current setting | Stops |
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
| coverage | floor | 88% line + branch, publish set | undertested code |
| interrogate | ratchet | 38 / 45 / 63 / 46 per tree | missing docstrings, per-subtree floors |
| suite inventory | identity ratchet | `docs/testing/SUITE-INVENTORY.md` | a suite silently ceasing to collect |
| enumeration coverage | identity ratchet | `scripts/check_enumerations.py` | a derived control list drifting from its source enum |
| doc links | floor | zero broken | a relative markdown link whose target does not exist |
| version consistency | floor | exact match | any version site disagreeing with `VERSION` |
| benchmark provenance | floor | pinned digests | a vendored IFEval/BFCL grader or corpus changing unnoticed |
| architecture fitness | floor | zero violations | a forbidden cross-layer dependency |
| execution lifecycles | identity ratchet | `quality/execution-lifecycles.json` | a new work-state enum nobody classified, or an entry left behind after its enum was deleted |
| Hypothesis conformance | floor | zero falsifying examples | a property violation in `formal/` |
| acceptance-criterion state | count ratchet | `quality/ac-state-ceilings.json` (7 counters) | a completion claim outrunning its evidence — and an unbanked improvement, so the ceiling holds no slack |
| Gherkin well-formedness | floor | zero parse failures | an acceptance-criteria block the Gherkin grammar rejects |

Vulture runs in two workflows but has one authority: the per-identity ledger
in `quality/vulture-baseline.json`, which records every reviewed finding as an
explicit `path::message` identity (line-number-independent, so unrelated code
motion doesn't trip the gate). A new finding fails CI by name; an identity
that no longer occurs also fails by name until pruned — the ledger can only
shrink, so it cannot retain slack that a later regression could consume, and
a same-count substitution is two named failures rather than an invisible swap.
`vulture-ratchet.yml` covers PRs and trunk pushes; the `quality.yml` step
extends the identical invocation to `feat/*` pushes. Bank a reviewed change
with `scripts/check-vulture-baseline.py --update <scan args>` and review the
JSON diff — never edit entries by hand to match a delta. (Until 2026-08 this
was a total-count ceiling plus a per-rule count+SHA-256 digest; the digest
caught substitutions but failures weren't legible per identity, and the count
ceiling held slack.)

## Acceptance-criterion state

`scripts/check-ac-state.py` measures what the other gates cannot: whether a
document's *status* is true. Everything above checks code. A front-matter
`status: Implemented` is checked by nobody, and was wrong on six consecutive
ADRs for months (#357, #363), because one person can assert it about a whole
document at once.

The unit of truth is pushed down to the individual acceptance criterion, where
it can be measured. Each criterion carries an `**AC-N**` id, tests claim it with
`@pytest.mark.ac("SPEC-xxx/AC-n")`, and the spec's `ac-modules` front-matter maps
it to the module it asserts about. From that the script climbs a ladder:

| Rung | Means |
|---|---|
| `declared` | the spec states it, with an id |
| `covered` | some test claims it |
| `passing` | that test passes |
| `reachable` | the module it asserts about is reachable from a real entry point |

The last rung is the one that matters and the one most easily left off. A green
test proves the code works; it does not prove anything runs it — `tick_decay`
(#344), `elevation_store` (#346) and the whole security pipeline (#350) were all
green, all tested, and all unreachable. A ladder stopping at `passing` would
reproduce that lie one level up, having spent the effort to get back here.

A document's **tier** is the highest rung *every* one of its criteria has
reached, so one lagging criterion holds the whole spec down. That is strict on
purpose, and it is why the report also carries the per-rung distribution: a tier
that reads `declared` does not say whether one criterion is missing or forty.
Spec tiers fold up to ADRs through each spec's `implements:`.

Two counts are reported separately and must not be merged:

- **contradicted** — the document claims `Implemented` and *has* measurable
  criteria that fall short. Its own artefacts refute it.
- **unverifiable** — the document claims `Implemented` and has nothing to
  measure yet. Unproven, not refuted.

Since #31 this is a **ratchet rather than a report**. Seven debt counters —
contradicted, unverifiable, specs awaiting AC-id retrofit, markers naming no
criterion, criteria ticked but unproven, Gherkin scenarios with no tag, and
Gherkin parse errors — are recorded in `quality/ac-state-ceilings.json` and may
only go down. A rise fails: a document started claiming more than its artefacts
support, and the fix is to prove the claim or correct the status, never to raise
the ceiling. An *unbanked improvement* fails too, for the reason the vulture
ledger stopped being a count ceiling: a margin left sitting there is slack that
a later regression spends invisibly. Bank one with
`--ratchet --bank` and read the diff.

The ratchet refuses to compare across measurement modes. Without `--run-tests`
no criterion can reach `passing`, so every claim above it reads as contradicted;
comparing those numbers against ceilings banked from a real run would make the
gate's verdict depend on how it was invoked. The mode is checked before anything
is measured, so a wrong-mode run leaves `quality/ac-state.json` untouched rather
than overwriting it with an unmeasured payload.

The starting ceilings are the debt as measured on 2026-08-22: **9 contradicted,
68 unverifiable, 139 specs awaiting retrofit**, 2 orphan markers, and zero on the
remaining three. Those are not targets — they are the line below which the
repository may not slip while the burn-down happens.

## Criteria are written in Gherkin

Not a new convention — the existing one, finally enforced. 11 documents already
carried 224 `Scenario:` blocks in ```gherkin fences, and `pytest-bdd` was
already a declared dependency of hive-conductor. Nothing read any of it: no step
definitions, no `.feature` files, no runner. Another built-but-never-wired
subsystem, this one inside the acceptance-criteria machinery itself.

So criteria are Gherkin, parsed with the real grammar rather than a regex —
the point of adopting a standard is that its own tooling decides what is
well-formed. That buys three things a prose bullet does not:

- **A structure that can be checked.** A `Scenario` with no `Then` states no
  observable outcome, so nothing about it is falsifiable. The report counts
  those separately from criteria that merely lack a test.
- **Tables instead of repetition.** `Scenario Outline` with an `Examples` table
  states a rule and its cases once. Four near-identical prose bullets become one
  criterion with four rows.
- **A path to executable criteria.** Valid Gherkin can later be bound with
  `pytest-bdd` without rewriting anything. That is deliberately *not* done here:
  step definitions are a large glue layer, the repo has 8,700 plain pytest
  tests, and the marker binding already works. The option is kept open, not
  taken.

A criterion's identity is a Gherkin **tag** — `@AC-3` above the scenario — never
the scenario's name. Names get reworded, and a reworded name would silently
break the binding to the test claiming it: the criterion would drop back to
`declared` with nothing saying why. One criterion may carry several scenarios.

Bullet-form `**AC-N**` criteria still count while the corpus converges, and the
report says which form each spec uses so the progress is visible rather than
normalised away.

Report-only for now: nothing fails a build, and no status is rewritten. Most of
the corpus is still prose-only, so the honest first pass is finding out what is
true. Run it with `--run-tests` — without that flag the `passing` rung is never
settled and every criterion stops at `covered`, which the report says on its
first line rather than leaving you to infer.

Security scanning (bandit, semgrep, gitleaks), dependency audit (pip-audit),
container scan/SBOM/cosign, and mutation testing run in their own workflows —
`security.yml` and `mutation.yml`.

## Why a ratchet rather than a clean sweep

Several baselines are large. They are the honest count of a backlog that
predates the gate, and the point of recording them is that the number can only
go down. Lowering one is ordinary work; raising one requires saying so in a
diff.

Two rules follow from that, and they are the ones most often got wrong:

- **Fix at the source, not in the baseline.** A new finding is a reason to
  change the code. Adding it to a baseline is for a finding that is genuinely
  intended — a library-only surface, test scaffolding — and then it wants a
  note saying which.
- **Shrink the baseline in the same pull request as the improvement.** The
  identity-keyed ratchets enforce this; the count-keyed ones cannot, so it is on
  the author.

## Running them locally

The gates are ordinary scripts. Nothing here needs CI:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/maistro-core/src   # …and the other eight packages/*/src
uv run python scripts/check-radon-baseline.py
uv run python scripts/check-reachability.py
uv run python scripts/check-convergence-matrix.py
uv run python scripts/check-reachability-dispositions.py
uv run python scripts/check-backlog-consistency.py
uv run python scripts/check-execution-lifecycles.py
uv run python scripts/check-suite-inventory.py
uv run python scripts/check-doc-links.py
uv run python scripts/bump_version.py --check
uv run python scripts/check-vulture-baseline.py packages/*/src \
  --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-ac-state.py --run-tests --ratchet
```

`scripts/check-suite-inventory.py --update` rewrites the inventory from an
actual collection. Always regenerate it that way — never by adjusting the
number by hand to match a delta, which defeats the point of the gate.
