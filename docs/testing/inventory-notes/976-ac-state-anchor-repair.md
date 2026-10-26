---
inventory-delta:
  packages/maistro-core/tests: +0
---
# #976 repair round: AC anchors re-homed to SPEC-102426-976a (no collection delta)

## What changed and why

The hosted ac-state gate failed at `dad86e6f0` on two counts, both
reproduced locally with CI-exact arguments (Postgres at
`127.0.0.1:5432`, `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` set,
`--run-tests --ratchet --mandate 4de7e906d9dc`):

1. `markers_without_criterion: 8 exceeds the ceiling of 2` — the six
   `@pytest.mark.ac("#976/AC-n")` anchors introduced by this branch named no
   declared criterion: no document carries the id `#976`, and the registry's
   id grammar (`^(ADR|SPEC)-NNN$` / `^(ADR|SPEC)-MMDDYY-xxxx$`) forbids ever
   having one. Debt counters fold by `min`, so the regression could not be
   banked away; the anchors had to resolve to real criteria.
2. `design_coverage: 44.2377 vs floor 39.641` — the unbanked improvement the
   prior round already recorded.

The repair re-homes the markers, it does not add or remove tests:

- new `docs/specs/SPEC-102426-976a-extension-telemetry-attribution.md`
  declares **AC-1**…**AC-6** from the issue's acceptance list, with
  `ac-modules` anchors on
  `maistro.capabilities.providers.extension_attribution`,
  `maistro.observability.correlation`, `maistro.events.envelope`, and
  `maistro.capabilities.provider_adapters`, `implements:` ADR-104 and
  `substrate:` ADR-083026-1cb1 (both Accepted, so the citation and
  absent-link mandates stay clean);
- the 25 existing `@pytest.mark.ac` markers in
  `tests/extensions/test_attribution.py` (15) and
  `tests/capabilities/test_provider_adapters.py` (10) move from the
  `#976/` prefix to `SPEC-102426-976a/`, one-to-one, same AC numbers, same
  tests;
- `quality/ac-state-notes/auto-976.json` banks the measured state
  (`design_coverage: 44.2377`, `markers_without_criterion: 2`), written by
  the gate's own `--bank` mode.

## Inventory delta

Zero. Marker text is not collection identity: `check-suite-inventory.py`
reports the same 17,832 collected node IDs for `packages/maistro-core/tests`
before and after, and the unique-evidence report is unchanged. No test was
added, removed, renamed, or re-parametrized.

## Verification recorded

- `scripts/check-ac-state.py --run-tests --ratchet --mandate
  4de7e906d9dc…` exits 0: 10 debt counters on their ceilings, design
  coverage exactly on its (banked) floor, acceptance mandate "every criterion
  this change declares is proven" (6 added, 0 unproven), chain mandate clean;
- `maistro_registry.cli lint . --strict`, `tools/lint_lifecycle.py`,
  `check-citation-status-provenance.py`, `check-adr-index.py`,
  `check-adr-status-language.py`, `generate-spec-ac-defined-index.py`
  (index unchanged) all exit 0;
- the suite's 140 attribution/adapter/CLI cases pass unchanged.

## Addendum (2026-10-25): re-anchor after the develop sync to b1c89cdbc

Merging develop `b1c89cdbc` into this branch moved the mandate base and with
it the measured corpus: at the new head `aa0133cd8` the tree measures
`design_coverage` **39.641** (166 taken decisions), not the 44.2377 the
branch note had banked from the earlier stacked tree. The stale banked claim
raised the exact-target half of the ratchet above what the tree measures, so
`scripts/check-ac-state.py --run-tests --ratchet --mandate b1c89cdbc` failed
with `design_coverage: 39.641 falls below the floor of 44.2377`.

The repair is the gate's own remedy, nothing else: re-bank the branch note
via `--bank` at the current head. `quality/ac-state-notes/auto-976.json` now
records `design_coverage: 39.641` — the exact value develop's owner-authorized
`design_coverage@39.641` grant (issue #166, read at the base) permits, which
is what makes the fall land legally. Only that one JSON line changed; no test,
marker, spec, or ADR moved, so the inventory delta stays zero.

Verified at `aa0133cd8` + this note:

- the CI-exact command exits **0**: ratchet OK (10 debt counters on their
  ceilings, design coverage exactly on the granted floor, authorized floor
  printed), acceptance mandate OK (6 criteria added/newly claimed, 0
  unproven), chain mandate OK;
- the 175 attribution/adapter/binding/CLI cases pass;
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exits 0 (1297/1297 identities banked) and
  `check-suite-inventory.py --suite packages/maistro-core/tests` reports no
  delta.
