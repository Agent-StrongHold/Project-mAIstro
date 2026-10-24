# atomic-admission-1893 — CI-repair round: develop sync + gate reproduction, head 638b5738c

Repair round for the #1893 lane at branch `auto-1893`. Starting head
`82756b5adb6c90a47c5461f65f3521064fa785a5`, develop base `afffa6309` (dispatch),
arriving with an unfinished `git merge` of `origin/develop` (`774ae42fc`) and
four conflicted files. The only edits in this round are the merge resolutions
and this note. No test was added; suite inventory delta is 0.

inventory-delta:
  packages/maistro-core/tests: +0

## What was repaired

1. **Unfinished develop sync, resolved and committed (ef95944f2).** The four
   conflicts (`Dockerfile`, `Dockerfile.research`,
   `packages/hive-conductor/Dockerfile`, `quality/image-pins.json`) were the
   same functional change made on both sides: the age/docker-CLI builder
   `golang:1.27.2-alpine` → `1.27.3-alpine` at the identical digest
   `b8c9b82a…` (CVE-2026-111943, HIGH, fixed in go1.26.10/1.27.3). Resolution
   takes develop's (#1152) comment/ledger wording so the trunk provenance
   (`recorded_in: #1152`, index re-serialization note) stays canonical;
   per-arch content is identical on both sides. No conflict markers remain
   (`scripts/check-merge-markers.py` → ok, exit 0).
2. **develop moved again during the round (774ae42fc → b9cd15c60: #2256,
   #2238, #2197, #2252, #2137).** Second `git merge origin/develop`
   auto-resolved with zero conflicts (638b5738c). Verified against the
   AGENTS.md quality/ multiset warning: `git diff HEAD origin/develop --
   quality/` shows only the branch's own intentional deltas — the two #1893
   reachability grants (develop lacks them) and the five eliminated
   `admission_identity.py` vulture rows (develop still banks them; the
   candidate scan no longer produces those identities, so absence is what a
   scan-match requires). No develop-side row was silently dropped anywhere
   else; `durable-table-retention.json`, `image-pins.json` playwright row and
   `ratchet-authorizations.json` carry every develop row plus the branch's.

## Why the three red CI checks at 82756b5 fail and what proves the fix

- **`security` (workflow rollup)** failed because its `Supply chain
  (pip-audit)` child failed; it is not a SAST failure (all three SAST jobs
  were green).
- **Supply chain (pip-audit)**: reproduced locally at CI's exact ordering
  (`uv sync --locked --all-extras` state, `uv pip install pip-audit`,
  `uv pip freeze --exclude-editable`, `pip-audit --strict --format=json`,
  `scripts/pip_audit_gate.py`) on the merged tree → gate exit 0; the only
  advisory is the triaged `ecdsa==0.19.2 PYSEC-2026-1325`; dependency-usage
  leg OK (11 packages, 62 runtime deps, 4 dispositions). The pre-merge lock
  carried untriaged advisories; develop's lock refresh resolves them.
- **Container scan + SBOM + cosign**: all four trivy-scanned images rebuilt
  fresh from the merged Dockerfiles (no cache), scanned with trivy 0.73.0 at
  CI's exact gate (`--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1
  --ignorefile .trivyignore.yaml`): hive-conductor, maistro-engine,
  maistro-engine-research, maistro-rsi-runner → **0 findings, exit 0 each**.
  Grype 0.116.0 cross-check (`--fail-on high --only-fixed`) → exit 0 on all
  four. In-image evidence: `libexpat1 2.5.0-1+deb12u5` in maistro-engine (the
  #1152 buildx-cache diagnosis: the base-digest bump now merged invalidates
  the stale cached `apt-get upgrade` layer), `usr/bin/age`/`age-keygen` 0
  findings in the full hive-conductor image. CI's docker-run identity step
  passes on the built image (python 3.13.16, bip-utils 2.12.1, coincurve
  21.0.0, pynacl 1.6.2, ConductorSeed operational). Note: the job name keeps
  "cosign" but signing was removed — there is no cosign step to reproduce.

## Executed evidence at final head 638b5738c (all commands this round)

- `uv sync --locked --extra dev` → resolved clean after the uv.lock updates.
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
  → 3467 files already formatted.
- Focused leaf: `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` → 128 passed,
  3 skipped (DSN-gated PG legs; PG durability proof for those legs stands at
  the 9d4b4957 round and is not re-claimed here).
- `uv run pytest packages/maistro-core/tests/runs
  packages/maistro-core/tests/scheduling packages/maistro-core/tests/scheduling packages/maistro-core/tests/security
  -q` → 3165 passed, 406 skipped (covers the #364/#2256 access-scope code the
  merge brought next to the admission work).
- `uv run python scripts/check-suite-inventory.py` → ok: 21 suites match.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (base resolves to
  b9cd15c60, candidate 638b5738c; 1309 findings, unclassified 0,
  never_allowlist 0).
- `python scripts/check-image-pins.py` → 8 pins across 10 Dockerfiles, all
  registered; `tests/test_pinned_digest_references.py` → 8 passed.
- `python scripts/check-merge-markers.py` → ok.
- mypy at ci.yml's exact ten-tree argv (core, server, turing, canvas,
  bootstrap, registry, evolve, rsi, design, ext-harness) → Success: no issues
  in 1096 source files, exit 0. (A split per-tree invocation is NOT the gate —
  it reports import-untyped noise; run the single ten-tree command.)

## Residual risks / UNVERIFIED by construction

- A green GitHub CI run at this head remains the only proof of the full
  containers job end-to-end (buildx gha-cache behavior, observability image
  build, frontend license-SBOM leg, gates-ran rollup). Every scanner leg that
  failed at 82756b5 is reproduced locally green; the cache-bust mechanism is
  the one part only CI can execute.
- PG-gated legs of the focused file skip locally here (no DSN in this
  round's environment); the live-PG proof of record is the 9d4b4957 note.
- Branch remains 1042 commits ahead of origin/develop with the two merges;
  no push/PR action taken (lane prohibition), so the merge queue has not yet
  seen this state.
