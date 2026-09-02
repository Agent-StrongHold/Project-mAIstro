# M1 pre-cutover golden behavioral baselines

Issue #463 freezes the behavior that must survive authority convergence before
legacy runtimes are retired. These records are an oracle, not a second runtime:
they describe observable contracts and deliberately contain no product
implementation.

## Layout and immutability

`tests/golden_baselines/manifest.json` names the required baseline set and locks
each fixture by SHA-256. A fixture is versioned, carries the exact repository
commit from which its evidence was captured, and names the characterization
tests that prove the behavior existed at capture time.

Changing a locked fixture is therefore not a quiet test edit. The manifest hash
must change too, which makes semantic baseline movement explicit in review. A
future intentional behavior change should create a new fixture version and
record its reason rather than rewriting v1 in place.

## What v1 captures

The v1 set records four pre-cutover surfaces named by #463:

- **Builders:** artifact handoff, failure terminalization, same-run retry, and the
  review-to-implementation revision loop.
- **Conductor:** task submission identity, public lifecycle projection, and
  terminal WebSocket streaming.
- **Evolve:** startup refusal, cycle-error visibility with loop survival,
  successful cycle counting, and status projection.
- **Schedules:** nominal occurrence time, catch-up distinction, overlap-SKIP,
  and a fire producing a canonical Run carrying schedule provenance.

Every fixture also records the six review dimensions from #463:
observable outputs, lifecycle, durable IDs/provenance, errors/refusals,
cancellation, and restart. A dimension may be `captured`, `not-characterized`,
or `not-supported`; anything not captured requires a written reason. That is
intentional. The baseline must expose evidence gaps instead of turning absence
of evidence into a promise.

## Consuming the oracle

`tests/golden_baselines/contract.py` provides `assert_observation_matches`.
Issue #459 can execute equivalent scenarios against converged product boundaries,
normalize their observations, and feed them into this matcher. The matcher fails
closed on a missing required path, a changed value, a missing durable identity,
or an incompatible ordered sequence.

The contract suite includes planted negative candidates. In particular, a
Builders retry that silently creates a new logical Run is rejected, and a
schedule result that loses its durable Run identity is rejected. Those are
semantic regressions even if each product's isolated unit tests would otherwise
remain green.

## Retirement rule

A product retirement PR may cite these baselines only for dimensions marked
`captured`. `not-characterized` is a recorded gap, not parity evidence. If
retirement requires one of those dimensions, add a new characterization and a
new baseline version before removing the old authority.
