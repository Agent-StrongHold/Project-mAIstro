---
inventory-delta:
  tests/: +0
---

# Verifier round at head 7f5bc553d8 (hosted CI DevSkim/CodeQL failures diagnosed; acceptance re-proven)

No code or test delta in this round: the tree is exactly `7f5bc553d8`
("docs(cr-1532): record verifier round at e83abbd1d3") on top of the
develop-sync merge `8c85a1a0e1` (develop `8955cf07a2`, merge-base verified).
This note records the repair-round validation; the only edit is this note
(+0 inventory delta, no suite names recorded).

## Hosted CI failure disposition (the named repair target)

All four failures at runs 45652366205 / 45652366514 (2026-11-25 16:17 UTC)
are a transient GitHub code-scanning ingest outage, not code this PR can
affect — job-log evidence fetched live:

- DevSkim job 139339955711: the scanner step ("Run DevSkim scanner")
  **succeeded**; the failure step is "Upload DevSkim scan results to GitHub
  Security tab", which hung ~26 s after "Uploading results" (16:18:02 →
  16:18:28) and failed with **no `##[error]` line anywhere in the log**.
- CodeQL Advanced jobs 139339957922 / 139339958228 / 139339958283 (js-ts,
  python, actions): each died at the same point of "Perform CodeQL Analysis"
  — interpret finished, SARIF upload went silent mid-request with no error
  output. Same signature, same window.
- Control: CodeQL Advanced **succeeded** on this same branch at the prior
  head `4fb10be787` (run 45646270186, 15:32), and `git diff 4fb10be787
  7f5bc553d8` contains **zero non-docs changes**. develop push `c9636e99`
  (16:34) and twelve PR branches (16:46–17:16, incl. DevSkim runs) all
  succeeded minutes after our window.
- Every functional gate at `7f5bc553d8` passed: CI, quality, security,
  Vulture Ratchet, Gate C, Registry CI, Cage Guard, Formal Conformance,
  mutation, Integration Scope.
- Re-run disposition: re-running the workflows (rerun/workflow_dispatch) is
  a GitHub mutation this worker is prohibited from performing; the head is
  left untouched so the hosted PR snapshot keeps matching the review head
  (the preflight block from the previous round is resolved only while the
  head stays `7f5bc553d8`).

## Local re-validation executed this round (head 7f5bc553d8)

- `scripts/check-adr-status-language.py` (registry.yml:136 CI-exact) →
  `ok: 0 baselined body-status contradiction(s)`, rc 0.
- `scripts/check-adr-status-language-provenance.py` → metric v2, base
  `8955cf07a21e`, candidate `7f5bc553d8f1`, "empty unversioned legacy ledger
  (explicit zero-tolerance migration to v2)", 0 findings, rc 0.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (quality.yml:1609-1613 CI-exact) →
  1221 == 1221 reviewed identities, rc 0.
- `ruff check .` / `ruff format --check .` → clean (3659 files).
- `check-suite-inventory.py` no-args (ci.yml CI-exact) → 21/21 suites ok.
- pytest: status-language (84) + provenance + adr-index + auth-middleware +
  setup-first-run suites → 190 passed.
- AC-2/3/4 selection (-k "agrees or corpus or value or banner or prose or
  superseded") → 55 passed.
- Auxiliary gates: check-ratchet-provenance (55 consumers), contract
  markers, merge markers, citation status, ADR index, lint_lifecycle → all
  rc 0.
- Independent corpus absence: `grep -rcE '\*\*Status\*\*:' docs/adr
  docs/specs` → 0 files with any match (AC-1 re-proven without the gate).
- Red-proof (absence semantics, executed outside the tree via
  `audit(roots=<temp>)` on two real corpus docs — ADR-001 Superseded and
  ADR-002 Accepted — with 8 spellings inserted, all values agreeing with
  front matter): 16/16 flagged as `body-status-line` (bare, dash, star,
  plus, 3-space indent, `1.`, `2)`, blockquote), fenced code block exempt,
  categories 2/3 silent. AC-2/AC-3 hold against reachable behavior, not just
  fixtures.

## Residuals recorded (not repaired — out of scope for a docs-note round)

- Branch is one develop commit behind tip: `c9636e99` (#1621 abandoned-
  Attempt recovery activation) landed at 16:34 after this branch's merge
  point `8955cf07a2`. Merging it now would move the review head and re-stale
  the hosted PR snapshot (the exact previous preflight block). The branch
  already carries compatible CR1621 content (container.py
  `recover_abandoned_attempts` at :1334 and the matching vulture ledger row,
  proven by the green Vulture Ratchet at this head); integration resolves at
  merge time.
- `quality/public-routes.json` ends without a trailing newline on this
  branch (develop has one) — merge-resolution artifact of the intentional
  /v1/setup/ exemption narrowing (5746e76e8e, branch-only); the security
  workflow passed at this head, no gate reads the trailing newline. Left
  untouched (cosmetic; repairs must address actual evidence).
