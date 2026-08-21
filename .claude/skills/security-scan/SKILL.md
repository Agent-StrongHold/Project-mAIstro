---
name: security-scan
description: Comprehensive local security scan using the full permissively-licensed (MIT/Apache/BSD) OSS toolchain to reach Google Artifact Registry / Wiz parity — SAST (bandit, ruff-S, dlint, semgrep), secrets (gitleaks, detect-secrets, trivy), Python+npm supply-chain/SCA (pip-audit, osv-scanner, grype+syft, guarddog, npm audit), container IMAGE scanning (trivy image, grype, dockle), IaC/config (checkov, trivy misconfig), and malware (guarddog, yara). Includes the base-image + VEX/triage guidance needed to truthfully claim "zero Medium+". Argument-driven: pass a path/package/image, or omit to scan the whole repo.
---

The user wants a deep security scan. The argument is $ARGUMENTS (an optional path/package to scope; default: repo root `.`). This runs the full permissive-license OSS security stack — far beyond bandit alone — and mirrors `.github/workflows/security.yml` so a clean run here predicts a green CI security job.

**License policy:** every tool below is MIT, Apache-2.0, or BSD **except semgrep (LGPL-2.1)**, which is kept (invoked as a CLI, not linked) and flagged. Excluded on license grounds: trufflehog (AGPL), hadolint (GPL). `safety` (MIT tool, restricted vuln DB) is optional.

Each tool is optional — if a binary is missing, print `skipped (not installed: <install cmd>)` and continue. Never fail the whole scan because one tool is absent. Tools install via `pip install -r requirements-dev-tools.txt` (pip ones) + the Go binaries (trivy/grype/syft/osv-scanner/dockle via their install scripts) and `gitleaks`.

Set `TARGET=${ARGUMENTS:-.}` and `PYSRC` = the Python source under TARGET (exclude tests for SAST noise where useful).

## 1. Python SAST (static analysis of our code)

```bash
# bandit (Apache-2.0) — medium+ severity & confidence, matches CI strict 0-baseline
bandit -ll -r $TARGET 2>/dev/null
# ruff flake8-bandit rules (MIT) — overlaps bandit but near-instant; catches some bandit misses
ruff check --select S --no-cache $TARGET 2>&1
# dlint (BSD-3) — flake8 security plugin (DUO* rules: insecure subprocess, eval, yaml.load, etc.)
flake8 --select=DUO $TARGET 2>&1
# semgrep (LGPL-2.1, license exception) — taint/dataflow SAST with OWASP + secrets rulesets
semgrep --metrics off --error \
  --config p/security-audit --config p/owasp-top-ten --config p/secrets \
  $( [ -f tools/semgrep/maistro-rules.yaml ] && echo --config tools/semgrep/maistro-rules.yaml ) \
  $TARGET 2>&1 | tail -40
```
Note: `tools/semgrep/maistro-rules.yaml` is referenced by CI but may be absent — the `[ -f ... ]` guard skips it cleanly. If it's missing, say so (CI references it too — see the CI-parity note at the end).

## 2. Secret scanning

```bash
gitleaks dir "$TARGET" --no-banner --redact 2>&1 | tail -30          # gitleaks (MIT) — working tree
gitleaks git . --no-banner --redact 2>&1 | tail -20                  # (optional) git history
detect-secrets scan "$TARGET" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("results",{}); print("detect-secrets: %d files with potential secrets" % len(r)); [print(" ", f, [x["type"] for x in v]) for f,v in list(r.items())[:20]]'
```
detect-secrets (Apache-2.0) and gitleaks use different detectors — run both; cross-reference. High false-positive rate on test fixtures/example keys — triage, don't auto-action.

## 3. Supply chain / SCA (dependency risk — multiple distinct risks)

```bash
# Known CVEs in Python deps — pip-audit (Apache-2.0): PyPI Advisory DB
pip-audit 2>&1 | tail -30 || true
# Known CVEs across ALL lockfiles — osv-scanner (Apache-2.0): Google OSV.dev (broader than pip-audit)
osv-scanner scan source -r "$TARGET" 2>&1 | tail -40 || true
# SBOM + vuln scan — syft generates, grype scans (both Apache-2.0)
syft dir:"$TARGET" -o cyclonedx-json=/tmp/sbom.json -q 2>/dev/null && grype sbom:/tmp/sbom.json 2>&1 | tail -25
# Malicious-package / typosquat detection — guarddog (Apache-2.0): a DIFFERENT risk than CVEs
guarddog pypi verify "$TARGET/requirements.txt" 2>&1 | tail -25   # or per-package: guarddog pypi scan <name>
```
These cover different supply-chain risks: pip-audit/osv-scanner/grype = **known CVEs**; guarddog = **malicious code** (suspicious install hooks, typosquatting, exfil patterns); syft SBOM = **provenance**. Report them separately — a CVE is "upgrade me", a guarddog hit is "investigate this package now".

## 3b. npm / frontend ecosystem (do NOT skip — GAR/Wiz scan this)

The repo has React frontends (`packages/hive-conductor/frontend`, `packages/maistro-canvas/frontend`)
with their own `package-lock.json`. Python scanners miss these entirely.

```bash
for lock in packages/*/frontend/package-lock.json; do
  echo "### $lock ###"
  osv-scanner scan source "$lock" 2>&1 | tail -25            # OSV — npm CVEs
  ( cd "$(dirname "$lock")" && npm audit --omit=dev 2>&1 | tail -20 )  # npm registry advisories
  guarddog npm verify "$(dirname "$lock")/package.json" 2>&1 | tail -15 || true  # malicious npm pkgs
done
```

## 3c. Container IMAGE scanning — the GAR / Wiz parity layer (THE critical gap)

Google Artifact Registry (Container Analysis) and Wiz scan the **built image**, including OS packages
baked into the base layer — which source/lockfile scans CANNOT see. You will NOT match their findings
without this. Scan every Dockerfile's resulting image; if you can't build, scan the **base images** as
a proxy (they carry most of the OS CVEs).

```bash
# Base images in use: python:3.12-slim, node:22-alpine, mcr.microsoft.com/playwright:*-noble
for img in python:3.12-slim node:22-alpine; do
  echo "### trivy image $img ###"
  trivy image --scanners vuln,secret,misconfig --severity MEDIUM,HIGH,CRITICAL --no-progress -q "$img" 2>&1 | tail -40
  grype "$img" --only-fixed 2>&1 | tail -25            # grype cross-check (Anchore feeds)
  dockle --exit-code 0 "$img" 2>&1 | tail -20          # CIS image best-practices (non-root, no secrets, etc.)
done
# If images are built locally/in CI, scan the ACTUAL tag instead of the base:
#   trivy image --severity MEDIUM,HIGH,CRITICAL <registry>/<image>:<tag>
```

**Reality check — what it takes to truthfully say "zero Medium+":** `python:3.12-slim` (Debian) and
the Playwright/Ubuntu image carry HIGH/CRITICAL OS-package CVEs at any given time that you cannot fix
(they wait on upstream). To *mean* the claim you need one of:

1. **A continuously-patched minimal base** — `cgr.dev/chainguard/python` (Wolfi) scans to **0 CVEs**
   and is the highest-leverage fix. CAUTION: do NOT reach blindly for "distroless" — Google's
   `gcr.io/distroless/python3-debian12` is frequently *staler than `python:3.12-slim`* (measured 159
   CVEs incl. 5 CRITICAL vs slim's 109/2 — worse). Always scan the candidate base before adopting it;
   "distroless" is not a synonym for "fewer CVEs".
2. **A documented VEX / triage allowlist** — `.trivyignore` (CVE IDs) or an OpenVEX doc marking each
   unfixable base-image CVE as "not affected / won't fix" **with justification**. GAR and Wiz both honor
   this model; a bare suppression without justification does not count as "meaning it".

Run `trivy image --ignorefile .trivyignore ...` so the triaged set is explicit and reviewable, and
re-scan on a **schedule** (new CVEs publish daily — GAR/Wiz re-scan continuously; match that with a
nightly CI job, not just push-time).

## 3d. Malware / signature parity (Wiz)

```bash
guarddog pypi verify requirements.txt 2>&1 | tail -20   # malicious PyPI (heuristics + semgrep)
# yara-python is installed for custom signature rules; point at a ruleset if you maintain one:
#   python3 -c "import yara; yara.compile('rules.yar').match('<path>')"
```
(ClamAV is GPL — excluded on license grounds; guarddog + yara cover the permissive-license malware niche.)

## 4. IaC / config / container misconfiguration

```bash
# checkov (Apache-2.0) — Dockerfiles, GitHub Actions workflows, compose, secrets
checkov -d "$TARGET" --framework dockerfile,github_actions,docker_compose,secrets \
  --skip-path '.claude/worktrees' --skip-path '.venv' --compact --quiet 2>&1 | tail -40
# trivy (Apache-2.0) — all-in-one over the filesystem: vuln + secret + misconfig + license
trivy fs --scanners vuln,secret,misconfig,license "$TARGET" \
  --severity MEDIUM,HIGH,CRITICAL --skip-dirs '.claude/worktrees' --skip-dirs '.venv' -q 2>&1 | tail -40
```
This repo has Dockerfiles (root + `packages/hive-conductor/**`), several `docker-compose*.yml`, and
many `.github/workflows/*.yml` — checkov catches base-image pinning, GH-Actions permissions/injection,
and compose privilege issues that CI linters miss.

**Always pass `--skip-dirs/--skip-path .claude/worktrees` and `.venv`** — those hold dozens of
duplicate Dockerfiles/lockfiles (git worktrees + the virtualenv) that are gitignored and would 10×
the noise without adding signal.

## 5. Synthesize a ranked report

Do NOT dump raw tool output. Produce:

1. **Headline counts** per layer: SAST findings, secrets, dependency CVEs, malicious-package flags, IaC misconfigs.
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
- [ ] Every suppression lives in a reviewable `.trivyignore`/OpenVEX/baseline **with a written justification** (an un-justified ignore is not "meaning it").
- [ ] The image scan ran against a **current** pull (re-scan on a schedule — new CVEs land daily).

If base-image OS CVEs are the only Medium+ remaining, the honest statement is "zero Medium+ in our
code, deps, and config; N triaged upstream base-image CVEs tracked in VEX" — OR switch to a
distroless/Chainguard base to drive that N to zero. Do not silently drop the base-image dimension.

Map to the user's 12-step workflow step 11 (security) and the strict CI gates in `security.yml` (bandit 0-Medium+ baseline, semgrep `--error`, pip-audit strict).

## CI-parity notes (flag these if you see them)

- CI `security.yml` references `--config tools/semgrep/maistro-rules.yaml` and scans `services/` — both **may not exist** in the repo (no `tools/` dir; `services/` absent). If so, the CI semgrep step is broken or silently passing (its exit code is swallowed by `| tee`). Surface this; offer to create a starter `tools/semgrep/maistro-rules.yaml` (use the `semgrep-rule-creator` skill) and fix the scan paths.
- The full tool roster + licenses lives in `docs/specs/` if a security-tooling spec exists; otherwise this skill is the source of truth.
