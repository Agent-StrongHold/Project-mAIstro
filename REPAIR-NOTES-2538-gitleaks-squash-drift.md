# REPAIR-NOTES-2538 — Gitleaks findings on develop classified; SAST restored to green

Issue: #2538 (`[Security][P0] Investigate two Gitleaks findings on develop and
restore trustworthy SAST`). Lane L2538, exact head
`ab19f5dd5909533fc85a4c65eeb14ac764c4342f` (= develop base, no drift).
Local gitleaks binary **8.30.1** — the exact version `security.yml` pins by
SHA-256. No secret material is reproduced below; every value is elided and
only rule/path/commit/fingerprint metadata is recorded.

## Redacted report review and classification

`security.yml`'s third arm scans `gitleaks git --redact --log-opts="--all" .`
on every push to `develop`. The reported `leaks found: 2` (CI runs
45932853317 / 45988002173) reproduce exactly on the CI-visible ref set:

| # | fingerprint (commit:path:rule:line) | classification |
|---|--------------------------------------|----------------|
| 1 | `05df0ac31ba215c876a1ba406f6fa9c299b28628:packages/maistro-core/src/maistro/security/sentinel/integrity.py:generic-api-key:125` | false positive — Python type annotation |
| 2 | `05df0ac31ba215c876a1ba406f6fa9c299b28628:.../integrity.py:generic-api-key:194` | false positive — Python type annotation |

The two flagged lines are the `DecisionSigner` constructor and rotation
signatures — both take a parameter named for a private key, annotated with
the `cryptography` package's Ed25519 private-key type (transcribed here in
prose on purpose: quoting the signatures verbatim would make this document
trip the same rule; see the line numbers in `.gitleaksignore`). The
`generic-api-key` rule keys on the `…_key` name prefix followed by a long
token — here the *type name*, not a value. There is no literal to split: the
parameter accepts a key object the caller already holds, the signer generates
or derives its material at runtime, and durable records keep public
verification material only. This is the documented false-positive shape of the
SPEC-070626-5341 entry already in `.gitleaksignore`.

**No genuine credential is involved; nothing to revoke or rotate, no
access/audit exposure to assess.** Provenance: PR #2533 (M2-A4 Sentinel
tamper-evident decision signing), merged 2026-11-27.

## Root cause: squash-merge fingerprint drift

PR #2533 already carried a correctly-classified disposition, but keyed to the
**branch head** `5fac53cdb3` (lines 111/150). The merge was a **squash**
(`05df0ac3`), which re-cut the file — the same annotations sit at lines
125/194 there — so the entries stopped matching develop's history while
remaining load-bearing for the still-open `auto-69` branch, whose history the
`--all` arm keeps scanning. This is precisely the fingerprint fragility the
`.gitleaks.toml` header warns about; #441's open question ("an entry that is
genuinely inert should be distinguishable from one that is not") is the
systemic follow-up and is deliberately not re-implemented here.

## Remediation (governed disposition, no bypass)

`.gitleaksignore` gains exactly two entries — commit + path + rule + line,
the narrowest scope gitleaks supports — with the drift documented inline:

- `05df0ac3…:…/integrity.py:generic-api-key:125`
- `05df0ac3…:…/integrity.py:generic-api-key:194`

The two pre-existing `5fac53cdb3…:…:111/:150` entries are **retained**: the
commit is still reachable from `origin/auto-69`, which the `--all` arm scans,
so they remain load-bearing. A source rename of the public `private_key`
keyword could not have greened the gate (both commits are immutable history
the `--all` arm scans forever) and would have degraded the API for nothing.
No change to `.gitleaks.toml`; no rule disabled; no scan narrowed.

## Failing-to-green evidence

CI-equivalent scope (`--log-opts="--remotes"`, i.e. the origin refs an
`actions/checkout` with `fetch-depth: 0` materializes; the local checkout of
develop adds nothing not already in origin refs):

```text
BEFORE (at ab19f5dd, disposition absent):
  gitleaks git --redact --log-opts="--remotes" … .   → exit 1, leaks found: 2
    (exactly the two 05df0ac3…integrity.py fingerprints above)

AFTER (disposition added):
  gitleaks git --redact --log-opts="--remotes" … .   → exit 0, "no leaks found"
    (13003 commits, ~250.6 MB)
```

Superset `--log-opts="--all"` after the fix reports 3 remaining findings keyed
to commits reachable **only** from local branches that do not exist on origin
(`auto-1143`, `rb1277-backup-97e31c62`, `m1-1176-b1` — verified with
`git for-each-ref --contains`), so CI cannot see them:

- `97e31c62…:tests/graph/durable_runs/test_recovery_wakeup.py:276/:319` —
  synthetic fixture literals (a fake `api_key` inside an error-message string
  and its redacted mirror used to exercise credential redaction);
- `6b7877a8…:tests/tasks/test_idempotency.py:754` —
  `idempotency_key="shared"` task-creation fixture, no credential shape.

No dispositions were added for these: entries keyed to commits origin does not
have would be inert bookkeeping, and disposing findings CI cannot scan is
outside #2538's scope. If those branches are ever pushed, the gate will report
them and they should be classified then.

## Validation of scope fidelity

- `git for-each-ref --contains` proves none of the three local-only commits is
  reachable from any `refs/remotes/origin/*` ref.
- The pre-fix `--remotes` run reproduces CI's exact count (2), so the local
  reproduction is faithful to jobs 140290794085 / 140468421075.

## Why no pytest addition

The executable check for this change *is* the gitleaks gate in
`security.yml`; a unit test cannot pin this failure mode without the pinned
gitleaks binary (a fingerprint-vs-history structural check would have passed
on the pre-incident tree — the drift produced uncovered *findings*, not
invalid entries — so it would not fail against the regression it names, which
repo doctrine forbids shipping). No suite count changes; no inventory note is
required.

## Owner and residual risk

- Owner: repo security area (BlakeMatthews-dev), parent initiative #452;
  allowlist-hygiene follow-up remains #441.
- Residual risk: **none from the two classified findings** — no secret ever
  existed at the flagged locations. Residual exposure is limited to the two
  documented process risks: (1) future squash merges can re-cut files under
  active dispositions and re-open findings (detected by the gate, as this
  incident was; recovery is the same narrow fingerprint re-keying), and
  (2) the retained `5fac53cdb3` entries become inert if `auto-69` is deleted,
  at which point they are removable without behavior change.
- This repair does not close #2538 or authorize any history rewrite.
