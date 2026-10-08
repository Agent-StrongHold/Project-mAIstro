---
inventory-delta:
  packages/maistro-core/tests: +12
---
# #896 coverage-guided fuzzing harness (M8-A15 prototype)

Bounded research prototype: a deterministic, in-process, PEP 669
(``sys.monitoring``) coverage-guided mutational fuzzer plus a 12-check
evidence suite over two real parser boundaries —
``maistro.extensions.manifest.inspect_manifest`` and
``maistro.agents.store.InMemoryAgentStore.import_gitagent``.

New files, all under ``packages/maistro-core/tests/research/``:

- ``_fuzzlab.py`` — the reusable machinery: module-local line+branch coverage
  via ``set_local_events`` (one target module per campaign, never a global
  tool), libFuzzer-basics mutators, contract-based oracle (a finding is only
  an exception outside the target's documented rejection types), frozen
  ``CampaignResult``/``FuzzFinding`` records with replay-based
  reproducibility, and a Hypothesis comparison arm running the same target
  under the same monitor.
- ``test_m8a15_fuzz_research.py`` — seed-validity guards, bit-for-bit
  determinism, replay checks, the measured campaign/Hypothesis comparison,
  the two routed contract escapes (manifest ``RecursionError`` from deep
  nesting; GitAgent container escapes ``BadZipFile``/``NotImplementedError``
  outside the documented ``ValueError`` contract), frozen-record and
  advisory-marker guards, and an AST inertness scan proving no
  ``packages/*/src`` module imports the lab.

Experiment record, measured numbers, and the terminal INCUBATE disposition:
``docs/research/896-coverage-guided-fuzzing-parser-surfaces.md``. Research
artifact only — no production module changes, no authority touched.
