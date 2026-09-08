---
name: security-scan
description: Comprehensive local security scan using the full permissively-licensed (MIT/Apache/BSD) OSS toolchain to reach Google Artifact Registry / Wiz parity — SAST (bandit, ruff-S, dlint, semgrep), secrets (gitleaks, detect-secrets, trivy), Python+npm supply-chain/SCA (pip-audit, osv-scanner, grype+syft, guarddog, npm audit), container IMAGE scanning (trivy image, grype, dockle), IaC/config (checkov, trivy misconfig), and malware (guarddog, yara). Includes the base-image + VEX/triage guidance needed to truthfully claim "zero Medium+". Mirrors the real CI gate in .github/workflows/security.yml. Argument-driven: pass a path/package/image, or omit to scan the whole repo.
---

The user wants a deep security scan. The argument is $ARGUMENTS (an optional path/package to scope; default: repo root `.`). This runs the full permissive-license OSS security stack — far beyond bandit alone — and mirrors `.github/workflows/security.yml` so a clean run here predicts a green CI security job.

**License policy:** every tool below is MIT, Apache-2.0, or BSD **except semgrep (LGPL-2.1)**, which is kept (invoked as a CLI, not linked) and flagged — see the per-tool license roster in `requirements-dev-tools.txt`. Excluded on license grounds: trufflehog (AGPL), hadolint (GPL). CI also enforces this via `pip-licenses --fail-on='GPL;LGPL;AGPL'` in the containers job.

Each tool is optional — if a binary is missing, pre-check with `command -v <tool>` and print `skipped (not installed: <install cmd>)`; continue with the others. Never fail the whole scan because one tool is absent — but NEVER report a missing or failed tool as "clean". Python tools install via `pip install -r requirements-dev-tools.txt`; pinned install commands for the Go binaries (gitleaks, grype, syft) are in `.github/workflows/security.yml`.

**Exit-code discipline (non-negotiable):** every scanner writes its full output to `/tmp/<tool>.out` via redirect, then captures `rc=$?` **immediately after the redirect — never through a pipe** (`| tail` or `|| true` discards the exit code and is forbidden here). Only after capturing `rc` may you `tail` the output file. Classify each result:
- `rc=0` → clean.
- `rc≠0` **with findings in the output** → findings; report them.
- `rc≠0` **with no findings** (usage error, missing tool, bad path, network) → **tool failure** — say "tool failed, rc=N", never "clean".

Set `TARGET=${ARGUMENTS:-.}` and `PYSRC` = the Python source under TARGET (exclude tests for SAST noise where useful).

## 1. Python SAST (static analysis of our code)

```bash
# bandit (Apache-2.0) — Medium+ severity, matches CI's strict 0-Medium+ gate
# (CI scope: packages/maistro-core/src packages/hive-conductor/backend packages/maistro-server/src)
bandit -ll -r "$TARGET" > /tmp/bandit.out 2>&1; rc=$?
tail -40 /tmp/bandit.out; echo "bandit rc=$rc"
# ruff flake8-bandit rules (MIT) — overlaps bandit but near-instant; catches some bandit misses
ruff check --select S --no-cache "$TARGET" > /tmp/ruff-s.out 2>&1; rc=$?
tail -40 /tmp/ruff-s.out; echo "ruff-S rc=$rc"
# dlint (BSD-3) — flake8 security plugin (DUO* rules: insecure subprocess, eval, yaml.load, etc.)
flake8 --select=DUO "$TARGET" > /tmp/dlint.out 2>&1; rc=$?
tail -20 /tmp/dlint.out; echo "dlint rc=$rc"
# semgrep (LGPL-2.1, license exception) — same config set as CI (custom rules + public registries)
semgrep --metrics off --error \
  --config p/security-audit --config p/owasp-top-ten --config p/secrets \
  --config tools/semgrep/maistro-rules.yaml \
  "$TARGET" > /tmp/semgrep.out 2>&1; rc=$?
tail -40 /tmp/semgrep.out; echo "semgrep rc=$rc"
```
`tools/semgrep/maistro-rules.yaml` **exists in this repo** and is exactly what CI loads (`--config tools/semgrep/maistro-rules.yaml` in `.github/workflows/security.yml`). It is governed security configuration — see the protected-file rule at the end. With `--error`, semgrep exits nonzero on any finding; a nonzero rc with findings in `/tmp/semgrep.out` is a real result, not a tool failure.

## 2. Secret scanning

```bash
gitleaks dir "$TARGET" --no-banner --redact > /tmp/gitleaks-dir.out 2>&1; rc=$?
tail -30 /tmp/gitleaks-dir.out; echo "gitleaks dir rc=$rc"
gitleaks git . --no-banner --redact > /tmp/gitleaks-git.out 2>&1; rc=$?   # (optional) git history
tail -20 /tmp/gitleaks-git.out; echo "gitleaks git rc=$rc"
detect-secrets scan "$TARGET" > /tmp/detect-secrets.json 2>/tmp/detect-secrets.err; rc=$?
python3 -c 'import json; d=json.load(open("/tmp/detect-secrets.json")); r=d.get("results",{}); print("detect-secrets: %d files with potential secrets" % len(r)); [print(" ", f, [x["type"] for x in v]) for f,v in list(r.items())[:20]]'
echo "detect-secrets rc=$rc"
```
detect-secrets (Apache-2.0) and gitleaks use different detectors — run both; cross-reference. High false-positive rate on test fixtures/example keys — triage, don't auto-action. CI runs gitleaks (pinned v8.30.1, sha256-verified) over the git range/full history; `gitleaks dir` here scans the working tree as a complement.

## 3. Supply chain / SCA (dependency risk — multiple distinct risks)

```bash
# Known CVEs in Python deps — pip-audit (Apache-2.0), mirroring CI's freeze+strict invocation.
# The authoritative allowlist/verdict gate is scripts/pip_audit_gate.py — cite it in the report.
uv pip freeze --exclude-editable > /tmp/deps.txt; rc=$?
pip-audit --strict -r /tmp/deps.txt > /tmp/pip-audit.out 2>&1; rc=$?
tail -30 /tmp/pip-audit.out; echo "pip-audit rc=$rc"
# Known CVEs across ALL lockfiles — osv-scanner (Apache-2.0): Google OSV.dev (broader than pip-audit;
# picks up uv.lock and both frontend package-lock.json files)
osv-scanner scan source -r "$TARGET" > /tmp/osv.out 2>&1; rc=$?
tail -40 /tmp/osv.out; echo "osv-scanner rc=$rc"
# SBOM + vuln scan — syft generates, grype scans (both Apache-2.0). Capture each rc separately.
syft dir:"$TARGET" -o cyclonedx-json=/tmp/sbom.json -q > /tmp/syft.out 2>&1; rc=$?
echo "syft rc=$rc"
grype sbom:/tmp/sbom.json > /tmp/grype.out 2>&1; rc=$?
tail -25 /tmp/grype.out; echo "grype rc=$rc"
# Malicious-package / typosquat detection — guarddog (Apache-2.0): a DIFFERENT risk than CVEs.
# There is no root requirements.txt in this repo — verify the checked-in tool manifest,
# or scan named packages: guarddog pypi scan <name>
guarddog pypi verify requirements-dev-tools.txt > /tmp/guarddog.out 2>&1; rc=$?
tail -25 /tmp/guarddog.out; echo "guarddog rc=$rc"
```
These cover different supply-chain risks: pip-audit/osv-scanner/grype = **known CVEs**; guarddog = **malicious code** (suspicious install hooks, typosquatting, exfil patterns); syft SBOM = **provenance**. Report them separately — a CVE is "upgrade me", a guarddog hit is "investigate this package now".

## 3b. npm / frontend ecosystem (do NOT skip — GAR/Wiz scan this)

The repo has React frontends (`packages/hive-conductor/frontend`, `packages/maistro-canvas/frontend`)
with their own `package-lock.json`. Python scanners miss these entirely.

```bash
for lock in packages/*/frontend/package-lock.json; do
  echo "### $lock ###"
  osv-scanner scan source "$lock" > /tmp/osv-npm.out 2>&1; rc=$?
  tail -25 /tmp/osv-npm.out; echo "osv-scanner($lock) rc=$rc"
  ( cd "$(dirname "$lock")" && npm audit --omit=dev > /tmp/npm-audit.out 2>&1; rc=$? )
  tail -20 /tmp/npm-audit.out; echo "npm audit($lock) rc=$rc"
  guarddog npm verify "$(dirname "$lock")/package.json" > /tmp/guarddog-npm.out 2>&1; rc=$?
  tail -15 /tmp/guarddog-npm.out; echo "guarddog($lock) rc=$rc"
done
```

## 3c. Container IMAGE scanning — the GAR / Wiz parity layer (THE critical gap)

Google Artifact Registry (Container Analysis) and Wiz scan the **built image**, including OS packages
baked into the base layer — which source/lockfile scans CANNOT see. You will NOT match their findings
without this. CI already builds and scans four images in the containers job (`hive-conductor`,
`maistro-engine`, `maistro-engine-research`, `maistro-rsi-runner` — see `.github/workflows/security.yml`).
Locally, scan the **actual built tags** when possible; otherwise scan the real base images as a proxy:

```bash
# Actual base images in use (grep '^FROM' across Dockerfile, Dockerfile.research,
# Dockerfile.rsi-runner, packages/hive-conductor/Dockerfile):
#   python:3.13.15-slim-bookworm (Dockerfile), python:3.12-slim (Dockerfile.research, Dockerfile.rsi-runner),
#   node:22-alpine, golang:1.25.13-alpine, cgr.dev/chainguard/python:latest[-dev] (hive-conductor)
for img in python:3.13.15-slim-bookworm python:3.12-slim node:22-alpine golang:1.25.13-alpine cgr.dev/chainguard/python:latest; do
  echo "### trivy image $img ###"
  trivy image --scanners vuln,secret,misconfig --severity MEDIUM,HIGH,CRITICAL --no-progress -q \
    --ignorefile .trivyignore.yaml "$img" > /tmp/trivy-image.out 2>&1; rc=$?
  tail -40 /tmp/trivy-image.out; echo "trivy($img) rc=$rc"
  grype "$img" --only-fixed > /tmp/grype-image.out 2>&1; rc=$?
  tail -25 /tmp/grype-image.out; echo "grype($img) rc=$rc"
done
dockle --exit-code 0 cgr.dev/chainguard/python:latest > /tmp/dockle.out 2>&1; rc=$?
tail -20 /tmp/dockle.out; echo "dockle rc=$rc"
# If images are built locally/in CI, scan the ACTUAL tag instead of the base:
#   trivy image --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml <registry>/<image>:<tag>
```

**Reality check — what it takes to truthfully say "zero Medium+":** the Debian-based images
(`python:3.12-slim`, `python:3.13.15-slim-bookworm`) carry HIGH/CRITICAL OS-package CVEs at any given
time that you often cannot fix (they wait on upstream). This repo already adopted the mitigations —
`packages/hive-conductor/Dockerfile` builds on **`cgr.dev/chainguard/python`** (Wolfi, scans near-zero),
and the rest are gated by CI's nightly trivy/grype job. To *mean* the claim you need one of:

1. **A continuously-patched minimal base** — `cgr.dev/chainguard/python` (already in use for
   hive-conductor). CAUTION: do NOT reach blindly for "distroless" — a distroless tag can be *staler
   than `python:3.12-slim`*. Always scan the candidate base before adopting it; "distroless" is not a
   synonym for "fewer CVEs".
2. **A documented VEX / triage allowlist** — this repo's is **`.trivyignore.yaml`** (version-scoped
   CVE entries, each with a written `statement` justification and an `expired_at` date). CI passes
   `trivyignores: .trivyignore.yaml` on every image scan; a bare suppression without justification
   does not count as "meaning it".

Run trivy with `--ignorefile .trivyignore.yaml` so the triaged set is explicit and reviewable, and
re-scan on a **schedule** — CI already runs nightly (`schedule: cron "30 7 * * *"` in security.yml);
new CVEs publish daily and GAR/Wiz re-scan continuously.

## 3d. Malware / signature parity (Wiz)

```bash
guarddog pypi verify requirements-dev-tools.txt > /tmp/guarddog-malware.out 2>&1; rc=$?
tail -20 /tmp/guarddog-malware.out; echo "guarddog rc=$rc"
# yara-python is installed (requirements-dev-tools.txt) for custom signature rules;
# point at a ruleset if you maintain one:
#   python3 -c "import yara; yara.compile('rules.yar').match('<path>')"
```
(ClamAV is GPL — excluded on license grounds; guarddog + yara cover the permissive-license malware niche.)

## 4. IaC / config / container misconfiguration

```bash
# checkov (Apache-2.0) — Dockerfiles, GitHub Actions workflows, compose, secrets
checkov -d "$TARGET" --framework dockerfile,github_actions,docker_compose,secrets \
  --skip-path '.claude/worktrees' --skip-path '.venv' --compact --quiet > /tmp/checkov.out 2>&1; rc=$?
tail -40 /tmp/checkov.out; echo "checkov rc=$rc"
# trivy (Apache-2.0) — all-in-one over the filesystem: vuln + secret + misconfig + license
trivy fs --scanners vuln,secret,misconfig,license "$TARGET" \
  --severity MEDIUM,HIGH,CRITICAL --skip-dirs '.claude/worktrees' --skip-dirs '.venv' -q > /tmp/trivy-fs.out 2>&1; rc=$?
tail -40 /tmp/trivy-fs.out; echo "trivy fs rc=$rc"
```
This repo has Dockerfiles (root `Dockerfile`, `Dockerfile.research`, `Dockerfile.rsi-runner`,
`packages/hive-conductor/Dockerfile`), `docker-compose*.yml`, and many `.github/workflows/*.yml` —
checkov catches base-image pinning, GH-Actions permissions/injection, and compose privilege issues
that CI linters miss.

**Always pass `--skip-dirs/--skip-path .claude/worktrees` and `.venv`** — `.gitignore` excludes
`.claude/*` (except skills/settings) and `.venv/`; those hold duplicate Dockerfiles/lockfiles and the
virtualenv that would 10× the noise without adding signal.

## 5. Synthesize a ranked report

Do NOT dump raw tool output. Produce:

1. **Headline counts** per layer: SAST findings, secrets, dependency CVEs, malicious-package flags, IaC misconfigs — **with each tool's `rc`**, and any tool failure called out as "tool failed", not counted as clean.
2. **Critical / High first**, each with `file:line` (or `package@version → fixed-version`), the tool that found it, and a one-line fix.
3. **Cross-tool corroboration** — when bandit + ruff-S + semgrep all flag the same line, rank it higher; when only one does, note the confidence.
4. **Triaged false positives** separately (test fixtures, example keys, `__exit__` params, intentional `exec` in benchmark harnesses).
5. **License-excluded coverage gaps** — note that trufflehog (AGPL) and hadolint (GPL) were intentionally not run, and what (if anything) that leaves uncovered.
6. **Skipped tools** with one-line install commands.
7. **Verdict**: is TARGET clean enough to push, or are there must-fix Critical/High items?

**The "zero Medium+, and mean it" checklist** — only claim it when ALL hold:
- [ ] SAST (bandit/ruff-S/dlint/semgrep): 0 Medium+ on our code.
- [ ] Secrets (gitleaks + detect-secrets): 0 real findings (FPs triaged with justification).
- [ ] SCA — **both** Python (pip-audit + osv-scanner) **and** npm (osv-scanner + npm audit): 0 Medium+ unignored.
- [ ] Malicious packages (guarddog pypi + npm): 0 flags.
- [ ] **Container image** (trivy image + grype on the ACTUAL built tags, not just base): 0 Medium+ unignored — this is the dimension GAR/Wiz weight most and the one most likely to fail.
- [ ] IaC/config (checkov + trivy misconfig): 0 Medium+.
- [ ] Every suppression lives in the reviewable **`.trivyignore.yaml`** (each entry has a written `statement` justification and an `expired_at` date — an un-justified ignore is not "meaning it").
- [ ] The image scan ran against a **current** pull (re-scan on a schedule — new CVEs land daily; CI's nightly job covers this).

If base-image OS CVEs are the only Medium+ remaining, the honest statement is "zero Medium+ in our
code, deps, and config; N triaged upstream base-image CVEs tracked in `.trivyignore.yaml`" — OR move
the remaining image to a Chainguard base to drive that N to zero. Do not silently drop the base-image dimension.

## CI parity (what `.github/workflows/security.yml` actually does — verified)

- **SAST job**: bandit `-ll --confidence-level=medium` over `packages/maistro-core/src`,
  `packages/hive-conductor/backend`, `packages/maistro-server/src` with a strict 0-Medium+ JSON gate;
  semgrep `--error` over **`packages/ tests/`** (not `services/` — that directory does not exist in
  this repo) with `--config tools/semgrep/maistro-rules.yaml` + `p/security-audit` + `p/owasp-top-ten`
  + `p/secrets`, excluding `packages/hive-conductor/eval` and `packages/hive-conductor/cage`; the step
  runs `set -o pipefail` before `... | tee semgrep-report.txt`, so **the exit code is NOT swallowed**;
  gitleaks (pinned, sha256-verified) over the PR/merge-group range or full history.
- **Supply-chain job**: `uv pip freeze --exclude-editable | pip-audit --strict`, gated by
  `scripts/pip_audit_gate.py` — the single source of truth for reviewed-CVE and unused-dependency state.
- **Containers job** (PR-to-main + nightly schedule): builds `hive-conductor`, `maistro-engine`,
  `maistro-engine-research`, `maistro-rsi-runner`; Trivy HIGH/CRITICAL `exit-code: 1` with
  `trivyignores: .trivyignore.yaml`; Grype `--fail-on high --only-fixed`; syft CycloneDX SBOMs;
  `pip-licenses --fail-on='GPL;LGPL;AGPL'`.

## Protected files — never overwrite

- **`tools/semgrep/maistro-rules.yaml`** is live, governed security configuration loaded by CI on
  every push. Do **not** create, overwrite, replace, or "repair" it. If you believe a rule is missing
  or wrong, report the proposed rule in your findings output (YAML snippet + rationale) and let the
  owner land it through review. Overwriting this file from a scan session is how a valid gate gets
  silently weakened.
- Same for `.trivyignore.yaml` and `.github/workflows/security.yml`: propose changes in the report;
  never mutate them as a side effect of scanning.

Tool roster + per-tool licenses: `requirements-dev-tools.txt`. CI gate behavior: `.github/workflows/security.yml` and `scripts/pip_audit_gate.py`. There is no separate security-tooling spec in `docs/specs/` — these three files are the source of truth alongside this skill.
