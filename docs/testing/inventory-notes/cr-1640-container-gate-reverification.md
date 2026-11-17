# CR-1640: container-gate re-verification at the post-merge head (round 2)

Verification record, no suite delta. Base `f927334a2e` (origin/develop);
head `b4f644367d7` (branch `chatgpt/1629-acceptance-delivery-planner`,
develop merged at `157c3f615be`/M1-E2).

Why a second round: every container-gate artifact produced before the
develop merge was stale. The merge changed real image inputs
(`Dockerfile` docker CLI 29.9.1 -> 29.9.3 with the x/net patch,
`Dockerfile.research`, `quality/image-pins.json` provenance re-attributed
to the #1373 refresh, and `uv.lock` moving graphql-core 3.3.1 -> 3.3.2,
joserfc 1.7.6 -> 1.8.0, pypdf 6.21.4 -> 7.1.0), while the previously
scanned images predated it and the research image had never been built
under the branch's own pins. All four scanned images were rebuilt from
this exact head and re-proven locally (shared WSL docker daemon;
daemon healthy, ~19 GB freed first by removing this lane's own stale
cr1640-tagged images):

- Builds (CI-faithful `--no-cache-filter` on the apt stage):
  `maistro-engine:pr-1640`, `hive-conductor:pr-1640`,
  `hive-conductor-observability:pr-1640`, `maistro-rsi-runner:pr-1640`,
  `maistro-engine-research:pr-1640` — all OK.
- Version/identity asserts (CI's exact one-liners): both Conductor
  images report python 3.13.18, bip-utils 2.12.2, coincurve 21.0.0,
  pynacl 1.6.2, `ConductorSeed.generate()` DID operational; the
  observability variant additionally imports opentelemetry + OTLP
  exporter. RC=0 both.
- Trivy `--severity HIGH,CRITICAL --ignore-unfixed --ignorefile
  .trivyignore.yaml --exit-code 1`: RC=0 on all four scanned images.
- Grype `--fail-on high --only-fixed`: RC=0 on all four. (First
  research-image run exited 1 on `no space left on device` inside the
  RAM-backed `/tmp` tmpfs during tarball extraction — environmental,
  not a finding; re-run with `TMPDIR` on disk passed. Remaining
  findings are Medium/Low/Negligible, under the high bar.)
- Lock reconciliation `check-image-lock-reconciliation.py` with CI's
  exact exports and member pins: RC=0 on all four ("ships exactly the
  locked set"; 126 / 73 / 220 / 147 distributions respectively).
- SBOMs (syft v1.49.0, four images + two frontend bundles + two npm
  trees) and `check-license-inventory.py` against
  `quality/license-policy.json`: RC=0, 8 surfaces, 25292 components,
  copyleft=419 (policy=review). Frontend surface is unchanged vs the
  base (empty `git diff f927334a..HEAD` over both frontend trees);
  bundle dists were built on this branch's frontend source.

Also green at this head locally:

- `python scripts/check-suite-inventory.py`: RC=0, 21/21 suites match
  (tests/ 6106 — the earlier +56 double-count is repaired by
  0a647a05db's delta deduplication; the gate's own failure mode at
  5439585f7 was reproduced and is what this repairs).
- `uv run pytest tests/test_plan_delivery.py -q`: 56 passed.
- `uv run ruff check .` / `ruff format --check .`: clean.
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact arguments): RC=0, 1238
  reviewed identities == 1238 findings, ratchet base 157c3f615be /
  candidate b4f644367d7.

Recorded as pending CI (not locally reproducible within budget, and
unchanged by this branch's delta): the ac-state mandate ratchet
(`check-ac-state.py --run-tests --ratchet --mandate <base>` — it
measures the base revision in a detached worktree with its own full
test run; refused without `--run-tests` when probed), the
diff-coverage gate, and the full root `test` job. Cosign signing is
removed by design (`.github/workflows/security.yml`; sign only when a
real registry push exists). No suite delta; no test added, removed,
renamed, skipped or weakened. Refs #1629.
