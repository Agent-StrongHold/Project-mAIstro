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
| model egress | identity ratchet | `quality/model-egress.json` | a new module calling a model endpoint directly, or an entry left behind after one was migrated |

The six architecture-fitness invariants of
[#36](https://github.com/Agent-StrongHold/Project-mAIstro/issues/36) are not all gates, and two
of them deliberately are not:

| Invariant | Enforced by |
|---|---|
| 1. No new universal execution lifecycle | `check-execution-lifecycles.py` |
| 2. No direct model/tool/effect provider bypass | `check-model-egress.py` (frozen set; the boundary itself is #56) |
| 3. No second durable Workspace/Event-sequence authority | **the type, not a gate** — `EventEnvelope.__post_init__` refuses a Workspace event that also defines a `stream_scope`, and the store refuses a caller-supplied sequence; both are covered in `tests/events/test_envelope.py` |
| 4. No unscoped durable project-owned objects | **the type, not a gate** — `Run` and `NodeRun` require a non-empty `project_id`, and `Run` rejects a graph snapshot whose `project_id` disagrees |
| 5. No outward core dependency-direction violations | `tests/fitness/test_import_boundaries.py` |
| 6. Compatibility owners not presented as canonical | convention: a compat alias carries the "Backwards compat aliases" banner |

Invariants 3 and 4 fail closed at construction, which is stronger than a CI sweep — the object
cannot exist in the wrong shape, so there is nothing for a gate to catch later. Adding one would
be a check with no signal, and a gate that never fires teaches people to ignore the ones that do.
| Hypothesis conformance | floor | zero falsifying examples | a property violation in `formal/` |
| acceptance-criterion state | count ratchet | `quality/ac-state-ceilings.json` (10 debt counters) | a completion claim outrunning its evidence — and an unbanked improvement, so the ceiling holds no slack |
| design coverage | **floor** | `quality/ac-state-ceilings.json` (`design_coverage`) | the proven fraction of the decided design *falling* — the one counter here where higher is better |
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

## The ratchet and the mandate

Two rules over one corpus, and the split is the point.

**The ratchet** (`--ratchet`) compares ten debt counters against
`quality/ac-state-ceilings.json`. It says *the repository did not get worse*.
It has never said *this change proved what it claimed* — a PR could add a spec,
tick a criterion `Implemented`, add no marker and pass, because the counter it
lands in already permits 68 of them. The ceiling absorbs the new debt silently.

**The mandate** (`--mandate <base>`) is zero tolerance on the criteria a change
**creates or newly claims**. Legacy criteria stay grandfathered on the ceilings
and fall over time; these are not legacy.

Ticking a box counts as touching a criterion even when its text did not move.
The tick *is* the claim, so it is exactly the moment to demand the evidence.

### Declaring one unproven

```markdown
<!-- ac-state: unproven AC-3 - blocked on the durable store (#132) -->
```

Per-criterion, reason mandatory, in the document body so it appears in the diff.
An escape hatch a reviewer cannot see is an unstated one.

### Two refusals worth knowing about

- **`--mandate` without `--run-tests` refuses.** Without a measured run nothing
  reaches `reachable`, so every touched criterion would look unproven. Failing a
  PR for a question that was never asked is worse than stopping.
- **An unreadable base refuses.** On a shallow clone every criterion looks new,
  which would demand the whole corpus be retrofitted in one PR — and a gate that
  fires on everything gets turned off. CI checks out with `fetch-depth: 0`.

### Why a new criterion cannot bank itself

`--bank` writes the `RATCHETED` counters. The mandate is not one of them: it is
a pass/fail over a computed set, not a number. So there is no path by which
today's unproven criterion becomes tomorrow's grandfathered debt — which, if it
existed, would make the escape hatch silent and the ratchet meaningless.

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

Since #31 this is a **ratchet rather than a report**. Ten debt counters —
contradicted, unverifiable, specs awaiting AC-id retrofit, markers naming no
criterion, criteria ticked but unproven, Gherkin scenarios with no tag, Gherkin
parse errors, and (since #164) specs implementing no ADR, taken ADRs with no
implementing spec, and specs declaring no criteria at all — are recorded in
`quality/ac-state-ceilings.json` and may only go down. A rise fails: a document started claiming more than its artefacts
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
68 unverifiable, 139 specs awaiting retrofit**, 2 orphan markers, 76 specs
implementing no ADR, 34 taken ADRs with no implementing spec, 7 specs declaring
no criteria, and zero on the remaining three. Those are not targets — they are
the line below which the repository may not slip while the burn-down happens.

## Design coverage — the one number that goes up

Everything above measures **debt**. Nothing above measures **distance**: how
much of the design the ADRs describe is implemented and proven. Without that,
"every green PR moves us closer to the designed future state" is an aspiration
CI cannot check, because there is no number that would have to rise.
Traceability plus non-regression is necessary and is not progress — *a PR that
changes nothing satisfies both*.

**ADR-082226-ff3c** defines it. For each ADR whose status is `Accepted` or
`Implemented`, take the fraction of its criteria — its own, plus those of every
spec whose `implements:` names it — that have reached `reachable`. Design
coverage is the **mean of those fractions**.

The choice that matters is the denominator:

| Formulation | Value | Denominator |
|---|---:|---|
| criterion-weighted, over ADRs that have criteria | 30.5% | 348 criteria belonging to 23 ADRs |
| **decision-weighted, every taken decision counts** | **3.96%** | 99 decisions; 94 of them score zero |

76 of 99 taken decisions declare no acceptance criteria anywhere. The first
number lets each of them vanish from its own denominator, so it reads
respectably while three-quarters of the design is unmeasured — and it is
gameable in the wrong direction, since deleting an unproven criterion *raises*
it. Under the decision-weighted form, a decision that declares no criteria
contributes **0**, and deleting every criterion returns it to 0.

Four consequences, all intended:

- **Every taken decision weighs the same.** A one-criterion ADR and a
  forty-criterion ADR are each one unit of design.
- **Writing criteria can only help.** An ADR at 0 with nothing written moves the
  moment one criterion is proven.
- **`Proposed` is excluded.** A decision not yet taken cannot be owed an
  implementation, and counting it would make writing an idea down look like
  incurring debt.
- **Accepting an ADR lowers the number**, because newly-owed work is now owed.
  This is correct, and it will feel wrong the first time it blocks a PR.

The bar is `reachable` and not `passing`: a passing test whose module the import
graph cannot reach proves the test runs, not that the system does.

The number is ratcheted by the same mechanism as the debt counters with the
inequality reversed — the recorded value is a **floor**, a fall is what fails,
and an unbanked rise fails too. A deliberate fall (retiring an ADR, accepting a
new one, discovering a criterion was never real) is banked with `--bank` and
justified in the diff. It is compared at four decimal places, which resolves
0.0001 against a smallest-real-move of 0.022 points, so proving one criterion
can never round away into a no-op.

**The starting value is 3.9582%, and it looks bad.** That is the honest reading
of a corpus where 94 of 99 taken decisions have nothing proven; a metric chosen
to flatter would not be worth ratcheting. The gap between it and the 30.5% is
itself the report — it names how much of the design has never been written down
as anything checkable.

Two things it does not say, both permanent: it says nothing about whether the
ADRs describe a *good* system, and a criterion can be tautological and still
reach `reachable`. This measures that evidence exists, never that it is
meaningful, which is why an approving human review stays in the merge path.

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
uv run python scripts/check-model-egress.py
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
