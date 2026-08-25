# Runner cost

**Status:** measured. Regenerate with

```bash
GITHUB_TOKEN=... python3 scripts/measure-ci-cost.py --pr <n>
```

This file answers the last open acceptance bullet of
[#161](https://github.com/Agent-StrongHold/Project-mAIstro/issues/161) —
*runner cost is measured before and after, with the deliberate exclusions
named*. The implementing PR reasoned about the cost and said it was reasoning;
the acceptance audit reopened the issue on that. See
[`ADR-082526-0d30`](../adr/ADR-082526-0d30-ci-runner-cost-is-measured-per-head.md)
for why it is measured this way rather than as a weekly total.

## What #161 changed

`ci.yml`, `quality.yml`, `security.yml` and `vulture-ratchet.yml` all declared
`pull_request: branches: [main, integration, develop]`. That filter matches on
the PR's **base**, so a PR stacked on a feature branch matched none of them and
ran two checks out of twenty-five.

The change removed the filters. It did not alter what any workflow *does*, only
which PRs trigger it — which is what makes the before and after both readable
off a single head. The old trigger set is a strict subset of the new one.

## Measurement

Head `cc819de` (PR #256, based on `develop`), 25 checks, all green.

| workflow | jobs | job-minutes |
|---|---:|---:|
| `ci.yml` | 13 | 18.4 |
| `quality.yml` | 5 | 13.7 |
| `formal-conformance.yml` | 1 | 1.8 |
| `security.yml` | 3 | 1.8 |
| `registry.yml` | 1 | 0.2 |
| `vulture-ratchet.yml` | 1 | 0.2 |
| `cage-guard.yml` | 1 | 0.1 |
| **total** | **25** | **36.3** |

| | job-minutes | checks |
|---|---:|---:|
| stacked PR, **before** #161 | 2.1 | 2 |
| any PR, **after** #161 | 36.3 | 25 |
| **marginal, per PR head** | **+34.2** | +23 |

A PR based on `develop` cost 36.3 job-minutes before the change too — it always
ran everything. The marginal cost falls entirely on stacked PRs, which is the
class that was previously cheap by being unmeasured.

**Wall-clock is not job-minutes.** The 36.3 job-minutes complete in **6m57s**,
because the jobs run in parallel. The floor under how fast a PR can go green is
the longest single job:

| job | wall-clock |
|---|---:|
| `test` | 6.9 min |
| `coverage (no services)` | 4.2 min |
| `Quality gate (Pillars 1–4, 7, 8)` | 3.8 min |
| `coverage (PostgreSQL)` | 3.0 min |
| `Coverage gate (publish-set floor + diff coverage)` | 2.1 min |

That floor is **unchanged** by #161: `test` already ran on every develop-based
PR. The change costs fleet capacity, not contributor latency.

### Billable minutes are zero

GitHub reports `total_ms: 0` for every job in this repository, so a cost stated
in money is zero. That is why the unit here is job-minutes: the real constraint
is contention for concurrent runners and the wait it imposes, and a truthful
"cost" has to name the thing actually being spent.

### One stale assumption, corrected

#161's scope names `hive-conductor-e2e-ui` as costing 20 minutes and proposes
keeping it base-filtered on that ground. Measured, it takes **1.8 minutes** —
below the median of the set. There is no cost argument for excluding it, and it
is not excluded.

## Deliberate exclusions

These were already named and machine-checked before this measurement;
[`REQUIRED-CHECKS.md`](REQUIRED-CHECKS.md) is the contract and
`scripts/check-required-checks.py` fails the build when it disagrees with
`.github/workflows/`. Every check runs on **every PR** except:

| check | scope | why |
|---|---|---|
| `Container scan + SBOM + cosign` | base `main` | job `if:` on `base_ref`; scans the image that is about to be released, which only a `main`-based PR is doing. Required on `main`, not on `develop`, so its `skipped` conclusion never has to be interpreted. |
| `Analyze (actions)` | base `main` | CodeQL, same release-gate reasoning |
| `Analyze (javascript-typescript)` | base `main` | " |
| `Analyze (python)` | base `main` | " |

No check is `paths:`-filtered any more; both that were, were fixed rather than
left advisory (`Registry CI` lost its filter, `Cage Guard` gained a success
path). The rule against reintroducing one is in `REQUIRED-CHECKS.md`.

## What is not measured here

What `concurrency: cancel-in-progress` saves. Every workflow above sets it for
pull-request events, so a superseded push stops paying immediately — this PR's
own history shows runs cancelled mid-flight on each new commit. But that saving
is a function of push frequency, not of one head, and a number derived from a
single run would be exactly the reasoned-about-not-measured figure that reopened
#161. Sizing it needs a window and a stated push-rate; it is not claimed here.
