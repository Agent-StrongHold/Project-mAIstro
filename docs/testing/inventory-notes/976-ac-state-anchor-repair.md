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
