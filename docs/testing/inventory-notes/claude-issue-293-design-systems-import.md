---
inventory-delta:
  tests/: +40
  packages/maistro-design/tests: +12
  packages/hive-conductor/backend/tests: +26
---
# claude-issue-293-design-systems-import

Seventy-eight new node IDs across five files, in three suites. Nothing removed or
reparametrised. Six of the conductor IDs are one parametrised test over
`BUNDLED_SLUGS`, so a seventh bundled system would move that count by one
without any file changing — the delta is against today's six.

The shape of the split follows the defect. The Conductor imported a module that
has never existed, a bare `except Exception` replaced it with a fabricated
design system carrying a real one's slug, and every gate in the repository
passed. So there is a test at each layer that let it through.

## `packages/hive-conductor/backend/tests` — the product (26)

`test_design_service_startup.py` (17) asserts through `DesignEngine.generate`,
the seam a `POST /design/projects` reaches, rather than by reading the registry
the service built. Startup succeeded before the fix too, so "it started" is
evidence of nothing; what changed is the prompt the model receives. Measured
against the pre-fix service, 8 of these 11 fail — the five systems that raised
`DesignSystemNotFoundError`, the two prompt-content assertions, and the one
that pins that a load failure is no longer swallowed into a substitute.

The three that pass either way are the interesting ones. `default` resolved
under the stub too, because the stub answered to its slug; an unknown slug
raised then and raises now; and `nodes.load_bundled is importer.load_bundled`
held all along, which is the point — the package had a working entry point the
whole time and the Conductor was the only caller reaching past it.

`test_design_systems_route.py` (9) covers the new `GET /design/systems`. Two
properties, both of them things the stub would have defeated: every entry names
its origin, recorded by the loader that read the files rather than inferred
from `trust_tier`; and a service that did not start answers 503 with the
recorded cause instead of an empty list. `test_a_status_with_no_cause_still_refuses`
is the case that matters most — degraded and unable to say why is still
degraded, and returning the list anyway is the failure this route exists to end.

## `packages/maistro-design/tests` — the library (12)

`TestOrigin` pins provenance at the layer that knows it. `TestTheIndexCoversTwoTiers`
resolves SPEC-234's open question: `catalog.json` indexes 150 systems and only
144 directories exist under `systems/catalog/`, because the other six are the
bundled set. Both counts were right about different things, and a caller
offering the index verbatim would offer six systems that resolve from nowhere.
`TestThePackagedFiles` covers the three data cases the AC names — present,
optionally absent (`design-tokens.json`), and malformed — with the malformed
case asserting that it raises rather than degrading, which is the library-level
statement of the behaviour removed from the Conductor.
`TestTheEngineExposesItsRegistry` pins the new `DesignEngine.systems` property,
which exists so the Conductor's route can report what is registered without
reaching into `_systems` across a package boundary.

## `tests/` — the gates (40)

`test_check_cross_package_imports.py` (26) tests the new resolver. Its two
failure directions are what the classes are organised around: a resolver that
stops finding the missing module lets the whole class back in, and one that
flags legitimate `__init__` re-exports gets waived everywhere within a week and
then deleted. `TestItLooksWhereTheBugWas` covers the placement specifically —
the real import was inside a function inside a `try`, so a walk that read only
module-level imports would have missed it.

`test_verify_wheel_imports.py` (14) covers the data-file half added to the
wheel verifier. Building wheels takes minutes, so these exercise the
declaration, the probe and the report against a fake install rather than
through `check()`; only the wiring between them needs a real build, and the
script's own end-to-end run in CI is that. Verified by hand against a real
build: the maistro-design wheel ships 24 bundled files and all 144 catalog
directories, and a declared-but-absent file fails the check.

`TestTheReport` exists because the split it tests was forced by the same
change. The failure list now carries JSON files as well as modules, so
"module(s) failed to import" became wrong wording on a line someone reads while
deciding whether a build is publishable — and a data failure printing an empty
traceback block reads as a truncated stack, which sends them looking for one.

`test_a_directory_does_not_count_as_a_file` is the one worth naming. `is_file`,
not `exists` — an empty directory left behind by a partial copy would otherwise
read as shipped, which is the same "looks complete" failure one layer down.
