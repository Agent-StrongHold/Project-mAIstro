# REPAIR NOTES — issue #1837 round at 5551fea7c (job 28b0310409fa) — Container gate

## Frozen scope

Only issue #1837, branch `auto-1837`, worktree `/home/dev/Git/wt/auto-1837`.
Exact starting HEAD `5551fea7c3f04ec15f3c32939617668fbc4fc4cd` (verified; tree
clean, exactly the dispatched head). Merge-queue named failure:
**`Container scan + SBOM + cosign`: failure** (job 120761070521, run
40056678808). No GitHub mutations; no Python/test changes (suite inventory
delta 0); no gate, ledger, grant, or workflow edits.

## Root cause (from the full CI log, then reproduced locally)

The failed job's failing step is the **third Trivy scan**
(`maistro-engine-research:pr-2268`). Job log
(`api .../actions/jobs/120761070521/logs`) shows the first two scans clean
(`hive-conductor` debian 0, `maistro-engine` debian 0) and engine-research
flagging exactly four HIGH findings (status `fixed`, so `ignore-unfixed`
does not skip them and the gate policy forbids allowlisting):

- OS (debian 13.7): `libbrotli1 1.1.0-2+b7` — **CVE-2026-111497** (brotli
  OOB write), fixed in `1.1.0-2+deb13u1`.
- python-pkg (dist-info METADATA): `pypdf 6.21.1` — **CVE-2026-115572,
  CVE-2026-115580, CVE-2026-115585**, all fixed in `6.21.2`
  (uploaded to PyPI 2026-10-21T16:44Z).

The `npm audit fix` lines in the dispatch digest are informational output of
the SUCCESSFUL `npm ci` in the hive-conductor frontend stage (npm does not
gate `npm ci` on advisory counts); they are not the failing process.

Timeline proof the brotli half is mirror-publish timing, not branch-caused:
the job's `production-apt` stage ran `apt-get update && apt-get upgrade -y`
at **2026-10-24T03:05:43Z** (log line `#14`), upgrading tzdata/lzma/
ca-certificates from updates that existed then; `trixie-security` published
`libbrotli1 1.1.0-2+deb13u1` in the Release dated **2026-10-24T04:00:57Z** —
55 minutes AFTER the apt stage consulted the mirror. The `--no-cache-filter
production-apt` mechanism (#795) re-consults the mirror on every candidate,
so a rebuild picks the fix up with no Dockerfile change.

## Repair (root cause)

- `uv.lock`: `uv lock --upgrade-package pypdf` — surgical 3-row diff,
  `pypdf 6.21.1 -> 6.21.2` (sdist+wheel hash/url/upload-time only). pypdf is
  a transitive of `browser_use` (core `browser` extra); no direct consumers
  in `packages/*/src`; not installed in the dev env (`uv sync` after the bump
  is a no-op), so no dev-env behavior change is possible.
- libbrotli1: no repo change — the published Debian security update plus the
  existing per-build `apt-get update` re-consultation is the fix; proven by
  rebuild + scan below.

## Local proof (gate-exact)

- Rebuilt `maistro-engine-research:pr-2268`
  (`docker build -f Dockerfile.research --no-cache-filter production-apt .`):
  image contains `pypdf 6.21.2` (venv metadata queried in-image) and
  `libbrotli1 1.1.0-2+deb13u1` (dpkg-query in-image).
- `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
  --ignorefile .trivyignore.yaml maistro-engine-research:pr-2268` — **exit 0**
  (trivy v0.73.0, the version the workflow pins; DB containing both CVEs).
- `maistro-rsi-runner` was never reached by the failed CI run; rebuilt and
  scanned the same way — **exit 0**, `libbrotli1 1.1.0-2+deb13u1` in-image.
- `hive-conductor` and `maistro-engine` scans were clean at this head in CI
  and ship no pypdf (their clean python-pkg tables at 6.21.1 in the lock
  prove they do not carry the affected distribution), so the lock bump is
  invisible to them; their CI evidence carries over.

## Gates re-run at the new tree (all exit 0)

`uv sync --locked --extra dev`; `ruff check .`; `ruff format --check .` (3484
files); `scripts/pip_audit_gate.py` on a fresh `pip-audit --strict` report
(only the triaged `ecdsa==0.19.2 PYSEC-2026-1325` remains, exactly as at the
previous round); `scripts/check-dependency-namespaces.py`; `scripts/check-
suite-inventory.py` (21 suites match); `scripts/check-adr-status-language.py`
+ `git diff --check` (the issue's own deterministic hygiene command).

## Issue acceptance re-verification (independent, not inherited)

The prior round's vector claim was re-executed from scratch against
`webauthn==3.0.1` (ephemeral env, script outside the tree): the ADR's
RECORDED canonical registration + assertion blobs verify with exactly the
recorded outcomes (credential_id/aaguid/fmt/sign_count/user_verified/
device_type/backed_up; assertion 0→1), and all six invalid vectors I1–I6
raise the recorded exception classes with **exact message-string equality**
to the ADR table. The ADR's recorded wheel digest matches PyPI's sha256 for
`webauthn-3.0.1-py3-none-any.whl`
(`9927b2f530773bd1d7f8194cd643a2e634a20995ea31f2d8f7a3e70b11c93e31`).
Owner acceptance itself remains the @BlakeMatthews-dev process gate — the
ADR correctly stays `Proposed` and #1837 stays open.

## Residual

None observed for this gate. Registry-side drift (a future advisory against
any shipped pin) is inherent to a scanner gate and is handled per-round by
the established root-cause-then-rebuild policy.

## Round 3 (job 977c8c4b7309437f) — fresh evidence at 1c000a686, post-race window

The hosted re-run identified above as the only remaining repair action had not
happened by this round; the merge-queue failure remains run 40074187701 job
120813931856 (rsi-runner `libbrotli1 1.1.0-2+b7`, CVE-2026-111497) from
07:41:21Z. This round re-proved the resolution mechanism FRESH, after the
deb.debian.org trixie-security propagation window had fully passed:

- `docker build -f Dockerfile.rsi-runner --no-cache-filter runtime-apt -t
  maistro-rsi-runner:pr-2268-r3 .` → in-image `dpkg-query -W 'libbrotli*'` →
  **1.1.0-2+deb13u1** (fixed version; the race window is closed — the mirror
  now serves the security update consistently).
- Gate-exact `trivy image --severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed --ignorefile .trivyignore.yaml maistro-rsi-runner:pr-2268-r3`
  (trivy v0.73.0, the workflow-pinned version) → **exit 0**.
- Same fresh proof for the research image: `docker build -f Dockerfile.research
  --no-cache-filter production-apt -t maistro-engine-research:pr-2268-r3 .` →
  `libbrotli1 1.1.0-2+deb13u1` + `pypdf 6.21.2` in-image; gate-exact trivy →
  **exit 0**.
- Hosted evidence at this exact head carries over for the other two images:
  in run 40074187701 `hive-conductor` and `maistro-engine` scanned clean, as
  did `maistro-engine-research`; only rsi-runner hit the stale CDN edge.
- Gates re-run at head, all exit 0: `check-adr-status-language.py` +
  `git diff --check` (the issue's own hygiene command), `check-adr-index.py`,
  `check-contract-markers.py`, `check-suite-inventory.py` (21 suites match),
  `check-dependency-namespaces.py`, `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (1302 identities = banked),
  `gitleaks git --redact --log-opts=4de7e906d..1c000a686 .` (no leaks),
  CI-exact pip-audit → `pip_audit_gate.py` (only triaged ecdsa
  PYSEC-2026-1325).
- Issue acceptance re-verified independently (not inherited): ADR-101826-c3f1
  recorded registration/assertion blobs replay under webauthn==3.0.1 with the
  recorded outcomes, I1–I6 refuse with **exact message-string equality** to
  the ADR table (8/8), and the recorded wheel sha256 matches PyPI byte-for-byte
  (`9927b2f5…c93e31`). Scope unchanged: no `webauthn` in `uv.lock`, no
  `packages/*/src` diff, Hybrid ADR-090726-9a4e diff empty, ADR still
  `Proposed`, no closure keywords in lane commits or PR body.

Residual action unchanged and now expected green: the next hosted evaluation
of `Container scan + SBOM + cosign` (a rebuild re-consults the mirror per
#795 and the race window has closed, as the r3 in-image versions above prove).

## Round 4 (job 70562a49a9024bd0a94b31182e0a309b) — reconcile-step repair proven at 4cb4b70a9

Named merge-queue failure at review head fe7020f5 (run 40096048976/job
120878426851): the "Reconcile installed packages to uv.lock" step (last step
of `Container scan + SBOM + cosign`; the four trivy scans and SBOM steps had
already passed) failed on its FIRST sub-command: `image maistro-engine:pr-2268
does NOT reconcile to the lock: version mismatch: beartype==0.22.9 (image)
!= beartype==0.23.1`. Root cause (prior round): develop's fastmcp 4.0.11->4.1.3
bump (461fb86b1) made beartype marker-split in uv.lock (0.22.9 for
`python_full_version < '3.15'`, 0.23.1 for `>= '3.15'`); `parse_expected` was
last-line-wins per name, so the py3.13 engine image installing the CORRECT
0.22.9 was failed against the collapsed 0.23.1 expectation. The repair at
4cb4b70a9 (already on this branch, one commit ahead of the PR-review head)
keeps every emitted pin per name and accepts any of them at reconcile; a
version outside the emitted set still fails, naming every branch.

Fresh, deterministic local proof at this exact head (tree clean at
4cb4b70a9d44649b150968ed0e6ccb9f201a2800):

- Exports regenerated with the workflow's exact invocations: the engine export
  carries `beartype==0.22.9 ; python_full_version < '3.15'` and
  `beartype==0.23.1 ; python_full_version >= '3.15'` at lines 132/136;
  research and rsi exports each carry the split; hive's carries none.
- All four images REBUILT from this exact tree with CI flags (apt stage
  `--no-cache-filter`): `maistro-engine:pr-2268-r5`,
  `hive-conductor:pr-2268-r5` (VITE_POC_MODE=pm, VITE_BASE_PATH=/pm/),
  `maistro-engine-research:pr-2268-r5`, `maistro-rsi-runner:pr-2268-r5`.
  In-image engine python is 3.13.16 with `beartype==0.22.9` (importlib.metadata).
- CI-exact reconcile step re-run end to end (all four sub-commands, workflow
  lines 493-540 arguments, `set -e`): ALL FOUR print
  `OK: ... ships exactly the locked set` and the step exits 0.
- Regression direction proven on the same real inputs: the PRE-fix script
  (extracted from parent fe7020f5a) run against the same fresh engine image +
  same fresh export fails with the byte-identical hosted error
  (`version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1`,
  exit 1). Root cause and fix are both demonstrated against production
  behavior, not mocked fixtures.
- Tests: `uv run pytest tests/test_check_image_lock_reconciliation.py -q` →
  32 passed at HEAD. In an isolated prefix running the same test file against
  the pre-fix script, the 4 outcome-bearing new tests FAIL there (and the
  behavior-preservation guard `test_marker_split_pin_absent_from_image_still_
  gates_nothing` passes on both sides, as designed); the inventory note's
  "all five fail" wording was corrected to "four of the five" in
  docs/testing/inventory-notes/1837-image-lock-marker-split.md this round.

Gates re-run at this head, all exit 0: `uv sync --locked --extra dev`,
`ruff check .`, `ruff format --check .` (3484 files),
`scripts/check-adr-status-language.py` + `git diff --check` (the issue's own
hygiene command), `scripts/check-adr-index.py`,
`scripts/check-contract-markers.py`, `scripts/check-suite-inventory.py`
(21 suites match), `scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (1302 identities = banked;
no ledger amendment warranted — the changed script is under scripts/, outside
the scanned surface).

Issue acceptance re-verified INDEPENDENTLY this round (not inherited): in an
ephemeral venv (`webauthn==3.0.1`, outside the tree), the ADR's RECORDED
registration blob verifies with every recorded field (credential_id bytes,
zero aaguid, fmt=packed, sign_count=0, user_verified=True,
single_device, backed_up=False) and the RECORDED assertion blob verifies
(new_sign_count=1, user_verified=True) against the registration's stored key;
I1-I6 replay with EXACT exception-class + message-string equality to the ADR
table (I3 via the appendix's signature-consistent regeneration, flags 0x41).
The recorded wheel digest matches PyPI's sha256 for
`webauthn-3.0.1-py3-none-any.whl` byte-for-byte
(`9927b2f5…c93e31`). The ADR remains `Proposed` (owner acceptance is the
@BlakeMatthews-dev process gate; not code-provable), `webauthn` stays
unlocked, and #1837 stays open — as the issue requires.

Residual action: the merge-queue re-evaluation of `Container scan + SBOM +
cosign` against a head containing 4cb4b70a9. Everything the failing step
executes has been re-run locally with CI-exact arguments and passes; the
remaining risk is only hosted-runner variance (registry/trivy-DB), not this
failure mode.

## Round-4 addendum — the same fix also landed on develop (f956a8142)

While recording this round, origin/develop advanced by
`f956a8142 WIP: [M2-A10][#75] Bound concurrent DAG Runs per principal and
Workspace (#2285)`, which carries an INDEPENDENT repair of the identical
beartype marker-split reconcile failure (its own evidence: merge-queue run
40085096483; same name -> set-of-emitted-versions semantics, "one of ..."
mismatch wording, 3 equivalent tests). Consequences for the next develop sync
of this branch (not performable here — no pushes):

- `scripts/check-image-lock-reconciliation.py` and
  `tests/test_check_image_lock_reconciliation.py` will conflict TEXTUALLY;
  the conflict is semantically benign — both implementations were proven this
  round against the SAME freshly built engine image + the SAME fresh export:
  this branch's 4cb4b70a9 script `OK ... exit 0`, AND develop's f956a8142
  script `OK ... exit 0` on identical inputs. Either resolution keeps the gate
  green; keep ONE implementation (develop's is already merged, so taking it in
  the sync is the natural resolution) and union or pick the test cases — both
  sets encode the same contract (both branches reconcile; outside-split fails).
- This branch's distinct deliverables (the gate-exact local proof, the
  inventory note, the corrected "four of five" wording) are additive docs and
  do not conflict.
