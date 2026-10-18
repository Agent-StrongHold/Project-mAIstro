# M8-A research note — coverage-guided fuzzing for parser and untrusted-input attack surfaces

Epic: #880. Leaf: #896 (M8-A15). Initiative: #879.

## Research question

Can coverage-guided fuzzing add value where MAIstro accepts raw or parser-heavy
untrusted inputs — especially where malformed byte/string structure matters more
than semantic state sequences — beyond what the existing Hypothesis baseline
already covers more maintainably?

## Targets

Two real MAIstro boundaries, both parsing raw, host-suppliable bytes with no
authenticator in front of the parser:

1. **`maistro.extensions.manifest.inspect_manifest`** — the extension-manifest
   parser (raw bytes → validated snapshot, or typed `ManifestRejected`). Its
   docstring contract is fail-closed: the only two outcomes are a validated
   snapshot or `ManifestRejected`; it gates what permissions an operator is
   shown, so any third outcome is a defect.
2. **`maistro.agents.store.InMemoryAgentStore.import_gitagent`** — the GitAgent
   zip import boundary (zip container + YAML manifest + UTF-8 payloads →
   `AgentIdentity`). Its documented rejection type is `ValueError`; the
   existing unit suite (`packages/maistro-core/tests/agents/test_store.py`,
   four cases) pins exactly that — but every one of those cases feeds a
   well-formed zip container.

Candidate targets not probed this leaf (recorded, not forgotten): warden
external-content parsing, protocol decoders, Canvas import/export, structured
tool-payload parsing. The two above were chosen because both are reachable from
operator-controlled bytes today and both have crisp, documented rejection
contracts — the prerequisite for a sharp oracle.

## Baseline

- **Existing unit suites**: manifest fail-closed tests; `import_gitagent`
  tests pinning `ValueError` for missing `agent.yaml`, path traversal,
  absolute paths, and non-dict manifests. All feed well-formed containers.
- **Hypothesis comparison arms**, measured in this experiment on the same
  targets under the same coverage monitor (250 examples, derandomized):
  generic `st.binary` and a recursive JSON-document strategy.

## Method — why a PEP 669 equivalent rather than Atheris

The issue allows "Atheris or a justified equivalent". Atheris is **not installed**
in this repository's locked uv environment and cannot be run in its deterministic
CI without adding a libFuzzer harness dependency; its primary differentiator
(libFuzzer/ASan instrumentation of native extensions) targets C-extension bugs,
while both probed boundaries are pure-Python parsers. The equivalent built here
(`packages/maistro-core/tests/research/_fuzzlab.py`, test-tree only) is the
libFuzzer loop in miniature, in-process, on stdlib only:

- **Coverage feedback via PEP 669 `sys.monitoring`**: line + branch events
  registered as *local* events on exactly one target module's code objects (a
  global tool fires on ~8,800 code objects and is ~3 orders of magnitude
  slower; local registration is what makes ~10⁵ execs/s possible). Objects
  are filtered on `__module__`, so imports (and `dataclasses`-generated
  methods attached to them) are never instrumented — every measured edge is
  attributable to the target module itself.
- **Corpus**: seeded with representative *valid* inputs (3 valid manifests;
  1 real GitAgent pack), grown by retaining any mutant that revealed coverage
  unseen so far.
- **Mutators**: the libFuzzer basics — bit flip, splice, region duplication
  (growth), truncation, interesting-byte extension, byte replacement.
  Deliberately structure-blind; directed structural probes exist precisely to
  measure what this misses.
- **Unguided control**: a seed-matched arm with the coverage feedback loop
  removed — same seeds, mutator, RNG stream, and exec budget, mutation drawn
  only from the seed corpus, nothing retained. Comparing discovered edges
  against it (not against the seedless Hypothesis arms) is what separates
  what guidance adds from what blind mutation volume over the same corpus
  reaches.
- **Oracle**: the documented rejection contract. `accepted` (returns),
  `rejected` (raised a documented rejection type), or **`escaped`** — an
  exception outside the contract is the experiment's only defect definition.
- **Determinism**: fixed RNG seed per campaign; same seed ⇒ same corpus
  growth, edge set, and findings (asserted bit-for-bit by the suite).

The machinery is advisory evidence by construction: nothing production imports
it (AST-scanned by a guard test), it reads no Goal/Run/authority state, and
`formal/` plus the existing Hypothesis suites remain the canonical property
authority — the Hypothesis arms here are a measurement of that baseline, not a
replacement.

## Measured results (CPython 3.12.14, seed 42)

### Manifest boundary — `inspect_manifest`

| Arm | Execs | Edges (seed → total) | Corpus | Accepted | Rejected | Escapes |
|---|---|---|---|---|---|---|
| Coverage-guided campaign | 4000 | 140 → **166** (+26) | 3 → 15 | 149 | 3854 | **0** |
| Unguided control (seeds/mutator/RNG/budget matched) | 4000 | 140 → **164** (+24) | 3 (fixed) | 578 | 3425 | **0** |
| Hypothesis `st.binary` | 250 | 7 | — | 0 | 250 | 0 |
| Hypothesis JSON documents | 250 | 20 | — | 0 | 250 | 0 |
| Directed deep-nesting probes | 2 | — | — | — | 1 | **1** |

- Byte-level mutation over valid-manifest seeds found **zero** contract
  escapes: the parser's fail-closed story held under 4000 structured-ish
  mutants. It also reached 166 parser edges vs 7–20 for the generic
  Hypothesis arms — coverage-guided mutation dominates generic generation on
  path discovery here (~8–24×) at comparable cost. Against the seed-matched
  unguided control the margin is honest but narrow: guidance retained a
  corpus that discovered +26 edges beyond the seeds where blind mutation
  over the same corpus discovered +24 — on this shallow, table-driven
  parser most reachable structure already sits in the seeds, which the
  disposition below weighs.
  The suite pins the ordering (`campaign.discovered_edges >
  unguided.discovered_edges`) so the claim cannot silently invert.
- **Defect found (routed, not fixed in this lane):** deeply nested JSON
  (`[[[...`, 20 000 deep) makes `json.loads` raise `RecursionError`, which
  `_parse_document` (`manifest.py:147`) does not catch — a third outcome the
  fail-closed contract does not admit. Byte-level mutation cannot build this
  input; only structure-aware generation reaches it. Severity: robustness
  (unhandled-exception path on operator-suppliable bytes), not an
  authorization bypass. **Route: extensions manifest surface (M9-B2, #953
  owners).** Note the deep-object shape (6 000 nested dicts) *is* properly
  rejected (`unknown manifest keys`) — the escape is array-specific.

### GitAgent boundary — `import_gitagent`

| Arm | Execs | Edges | Accepted | Rejected (ValueError) | Escapes |
|---|---|---|---|---|---|
| Coverage-guided campaign | 1500 | 82 → 88 | 439 | 248 | **814** |
| Hypothesis `st.binary` | 250 | 6 | 0 | **0** | 250 (all `BadZipFile`) |

- **Defect found (routed, not fixed in this lane):** the documented rejection
  type is `ValueError` (pinned by the existing unit suite), but container-level
  corruption escapes as `zipfile.BadZipFile` (first escape at exec 0) and
  unsupported compression/flag bytes escape as `NotImplementedError` from
  zipfile machinery (`store.py:201/215`). Campaign escape census: 801
  `BadZipFile` + 13 `NotImplementedError`; every recorded finding re-raises
  its exception on replay. Severity: robustness on host-suppliable bytes, not
  a traversal/permission bypass (the traversal guards themselves held: no
  mutant produced an accepted import with a traversal path). **Route: agent
  store GitAgent import/export surface.**
- **Corpus usefulness is visible here**: the Hypothesis binary arm never once
  reached a documented rejection path (0/250) — random bytes are not zips —
  while the seeded campaign exercised accept (439), reject (248), and escape
  paths, and discovered escape *classes* (`NotImplementedError`) Hypothesis
  never touched. Seeds carrying real structure are what make the mutation
  loop meaningful on container formats.

### Cost, reproducibility, oracle quality

- Runtime: full experiment ≈ 1.6 s wall (both campaigns + 3 Hypothesis arms +
  probes); the 12-test suite runs in ~7 s. CI cost is negligible.
- Reproducibility: bit-for-bit identical corpus growth, edge set, and findings
  for a fixed seed, asserted for both targets.
- Oracle quality: contract-based, so **false positives are impossible by
  definition** — a finding is only ever an exception outside the documented
  rejection types. The inverse risk is oracle blind spots: a parser that
  *accepts* hostile structure produces no finding; this technique measures the
  crash/oracle surface only, not semantic acceptance quality.
- Maintenance: the harness is one test-tree module (~470 lines) + one lab
  module; it pins live parser behavior, so seed rot fails loudly (seed-validity
  guard tests run before any campaign).

## What failure class does this catch that existing gates do not?

Exceptions escaping a parser's *documented rejection contract* on
container/byte-structure corruption — reachable by any host-suppliable input,
invisible to semantic-field unit tests (which feed well-formed containers) and
to generic Hypothesis strategies (which cannot build valid containers). The
directed probes additionally demonstrate the complementary gap: depth/structural
failures that byte-level mutation cannot reach, while pure Hypothesis never
builds 20 000-deep documents at all.

## Disposition: INCUBATE

Per the issue's deliverable constraint ("do not add broad fuzz infrastructure
if no concrete attack surface demonstrates incremental value"), the value side
is demonstrated narrowly, not broadly:

- **For incubating**: two real, host-triggerable contract escapes found on a
  live import boundary within 0.25 s of campaign time; ~8–24× path discovery
  over the Hypothesis baseline on the manifest parser (and strictly more
  discovered edges than the seed-matched unguided control); zero false
  positives by oracle construction; deterministic and CI-cheap.
- **Against graduating today**: both routed defects are unfixed (research
  lanes do not fix product code); byte-level mutation provably misses the
  depth-structural class (the manifest escape came from a directed probe, not
  the fuzzer); coverage counts here are module-local edge sets, not a
  libFuzzer-grade corpus format with minimization; and CI placement/ownership
  is undecided — these targets gate on *documented contracts* that their
  owning suites should pin after the routed defects are fixed, at which point
  a campaign like this becomes a regression harness rather than new
  infrastructure.

**Next required evidence** (what would move this to GRADUATE or REJECT):

1. The owning surfaces fix the two routed escapes and pin the repaired
   contracts (fail-closed for `inspect_manifest` on deep structures;
   `ValueError` (or a typed rejection) for container corruption in
   `import_gitagent`).
2. Re-run the same campaigns against the fixed boundaries: a clean campaign
   becomes the permanent periodic harness; if the fixes instead collapse into
   ordinary unit cases, the residual value of keeping the fuzzer shrinks
   toward REJECT.
3. A decision on which additional boundary (warden external-content parsing
   is the natural next candidate) shows escapes that unit tests do not —
   breadth beyond one boundary is what would justify shared infrastructure
   rather than per-leaf prototypes.

No disposition here authorizes production adoption inside M8; routing follows
the epic contract, and adoption would pass the normal architecture and
evidence gates.
