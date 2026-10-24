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
