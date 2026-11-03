# Repair #1836 round — rsi-runner trivy phantom root-caused and fixed (branch auto-1836)

Starting head `e82091c57d2695ed332d865305879ce59105632e` (assigned, clean), base
`4de7e906d9dc9f74ed47f240abc94221db102a66`. This round falsifies the previous
round's "scanner-side artifact, self-heals on re-run" conclusion (see
`repair-1836-round-trivy-revalidation.md`) with a third identical CI failure,
and fixes the actual mechanism. GitHub was read only; no mutations.

## The gate stayed red exactly as before — the artifact theory is dead

Run `40088280240` (job `120855557755`, head `e82091c57`, the same head the
prior round declared clean-by-rebuild) failed the `containers` job again on
`Trivy scan maistro-rsi-runner`: `libbrotli1 CVE-2026-111497 HIGH, installed
1.1.0-2+b7, fixed 1.1.0-2+deb13u1`. Three consecutive runs — 40066333928
(822547d), 40079655352 (73fd7bf3e), 40088280240 (e82091c57) — failed with the
same signature. A transient artifact does not reproduce three for three.

## Root cause (evidence, from the fetched job logs of both failing runs)

- In each failing job the rsi-runner build's own log shows the `runtime-apt`
  stage EXECUTING fresh (`#8`/`#7` RUN apt-get; trixie-security fetched,
  unpacked and set up libbrotli1 `1.1.0-2+deb13u1`), downstream stage-1
  re-running, a fresh manifest exported and `--load`ed. The scanned image
  nonetheless reported dpkg state `1.1.0-2+b7` — a version NO input of those
  builds could produce: the pinned base (`python:3.12-slim@a6e34c5`) does not
  contain libbrotli1 at all (apt log: "Selecting previously unselected"), and
  the only apt execution installed deb13u1. A b7 dpkg status can only come
  from an OLDER build's layer — i.e. the `type=gha,scope=rsi-runner` build
  cache, which has carried the pre-advisory `runtime-apt` result since before
  the fix published (ci.yml's rsi-runner build is cached with no
  `--no-cache-filter`, so it keeps re-writing that stale result).
- Scanner-side causes are excluded by the same job: the trivy DB cache restore
  was a MISS (`Cache not found for input keys: cache-trivy-2026-10-24`, fresh
  DB download), and the maistro-engine-research image — same trixie base,
  same libbrotli fix, same `--no-cache-filter` pattern — scanned CLEAN in the
  same job minutes earlier. Local fresh rebuild + CI-exact scan was clean
  (prior round) precisely because local builds have no GHA cache.
- Conclusion: the stage's buildx cache key (pinned base digest + RUN string)
  never changes, so the cached pre-advisory result stays valid-KEYED forever;
  `--no-cache-filter` forces the RUN to execute but does not guarantee the
  fresh result is the one the final stage binds to. The prior round treated
  the resulting scan-vs-log contradiction as a scanner bug; it is a stale
  build-cache binding.

## The fix (strengthens the gate; no suppression, no ignore-file change)

- `Dockerfile.rsi-runner`: the `runtime-apt` stage now takes
  `ARG SECURITY_PATCH_KEY` and writes `/etc/maistro-security-patch-key` in
  the SAME RUN that applies the OS patches — the stamp and the apt state are
  one layer and cannot diverge. The ARG participates in the stage's buildx
  cache key.
- `.github/workflows/security.yml` (rsi-runner build): passes
  `--build-arg SECURITY_PATCH_KEY=${{ github.run_id }}` — the stage's key is
  unique per build, so no cached result can exist for it and the fresh
  execution is the only possible parent — and no longer reads/writes the
  `rsi-runner` GHA build cache (the poisoned scope), keeping
  `--no-cache-filter runtime-apt` as defense in depth. release.yml already
  builds cold; ci.yml's unscanned `(cached)` rsi build still writes the
  scope but nothing gates on it.
- New verify step asserts the loaded image's stamp equals the current run id
  (and prints the installed libbrotli1 version as forensic context): any
  recurrence of this failure class now fails loudly at the build step,
  attributed, instead of as a scanner-vs-log contradiction at the trivy step.

## Local proof this round

- Binding experiment (local buildx, DOCKER_HOST per repo docs): build with
  key `run-111` → apt executed, stamp `run-111`; rebuild SAME key → all
  stages CACHED (proves the ARG is in the key); rebuild with new key
  `run-222` → apt re-executed and the FINAL image carries stamp `run-222`
  and `libbrotli1 1.1.0-2+deb13u1` (fresh parent bound) despite a cached
  `run-111` result existing locally. In CI a per-run key has no cached
  entry anywhere, so this is the structural guarantee, not a hope.
- `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
  --ignorefile .trivyignore.yaml` with trivy 0.73.0 (CI-pinned) on the
  freshly built image → **rc 0**, zero HIGH/CRITICAL, dpkg shows deb13u1.
- `uv run pytest tests/test_buildx_build_retry.py
  tests/test_check_build_context.py tests/test_dependency_namespaces.py
  tests/test_image_lock_contract.py tests/test_prepull_base_images.py
  tests/test_prepull_copy_sources.py tests/test_pinned_digest_references.py
  tests/test_check_image_inventory.py tests/test_check_gates_ran.py
  tests/test_branch_policy.py -q` → 369 passed. Workflow YAML parses; both
  touched run-blocks are shellcheck-clean.

## Issue #1836 acceptance re-validation at this head

- Deterministic command: `uv run python scripts/check-adr-status-language.py
  && git diff --check` → rc 0.
- SPEC-101826-1836 rev 5 golden vectors re-executed from the document's own
  recipes against the production helper: V-1 bytes+digest, V-2 reordered
  maps, all 11 V-3…V-13 mutations (pairwise distinct), V-14, all 8 V-15
  rejection rows with exact path-naming TypeErrors, V-16 v1 collision,
  V-17 ensure_ascii pin, V-18 legacy row (production helper AND live
  `DurableApproval` fallback resolve `1748e5b5…`). 32/32 checks pass. The
  vectors live in the document only — no implementation was added; the gate
  explicitly forbids claiming implementation tests.
- CI-exact vulture ledger scan (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → rc 0
  (1302 reviewed == 1302 findings, 0 unclassified, 0 never-allowlist): the
  CI-repair ledger clause is vacuous, no `quality/` amendment made.
- `check-suite-inventory.py` → ok, 21 suites match (34125 identities), no
  delta — no inventory note owed. ruff check + format --check clean.
- Decision-gate posture unchanged by design: SPEC status `Proposed`,
  `contracts: []`, owner acceptance open with the ADR owner; downstream
  #1837/#1838 stay blocked by the gate.

## Residual

- The other three scanned images (hive-conductor ×2, engine, research) keep
  the #795 `--no-cache-filter` pattern unchanged: their scans were green in
  every observed run, so no evidence-based change was made to them; the same
  one-ARG-plus-stamp repair applies per image if the class ever surfaces
  there.
- Hosted CI verification of this repair happens on the next merge-queue
  evaluation (writer may not push); the binding assertion converts any
  recurrence into an immediate attributed failure.
