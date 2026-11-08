---
inventory-delta:
  tests/: +0
---

# cr1532-verifier-validation-535ffb5a

Independent verification round for PR #1532 (retire body status lines,
ADR-092126-a28a) at head `535ffb5a4d4958b6ad995328d64a4570c604b4f6` against
merge base `78133c093e0a5cd0d2a7e8538afa703521c70d07`. No tests were added or
changed; deltas are all zero. This round re-proves the October correction
round (indentation grammar, metric v2 fail-closed, `(#1532)` marker) at the
current head, which the previous note (`cr1532-verifier-validation-d3b5`) did
not cover.

Gates re-run with CI's exact arguments, all exit 0:

- `python scripts/check-adr-status-language.py` (registry.yml) — 0 baselined,
  no new, none stale.
- `scripts/check-adr-status-language-provenance.py` — metric v2; candidate
  535ffb5a; trusted base 78133c093; the empty unversioned legacy ledger
  migrates explicitly with zero tolerance.
- `scripts/check-ratchet-provenance.py` — all nine ratchets (adr-status-
  language v2, citation-status, promotion-surface 432 modules, reachability
  102/1477, shell-execution 3, contract-markers 358, enumerations 1,
  lifecycle 0) plus 55 quality JSON consumers.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1253 reviewed identities,
  1253 findings, unclassified 0; no ledger amendment needed (develop's #2321
  vulture prune folded in, 1256 → 1253, ledger tracks exactly).
- `scripts/check-contract-markers.py`, `scripts/check-suite-inventory.py`
  (21 suites match), `tools/lint_lifecycle.py`, `scripts/check-adr-index.py`,
  `scripts/check-merge-markers.py`, `scripts/check-citation-status.py`,
  `scripts/check-citation-status-provenance.py`, `scripts/check-doc-links.py`,
  `scripts/check-release-consistency.py`.
- `uv run python -m maistro_registry.cli lint . --strict` — 444 files, 0
  errors, 0 warnings.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- Targeted suites: `tests/test_check_adr_status_language.py` (84),
  `tests/test_check_adr_status_language_provenance.py` (16),
  `tests/test_check_adr_index.py` — 119 passed.

Behavioral red-proof, run in a temp directory against the production
`audit(roots=...)` entry point with real validator-valid corpus ADRs as
fixture bases (Accepted and Superseded), 27/27 as ADR-092126-a28a specifies:

- Flagged `body-status-line`: agreeing bare line (AC-2), dash/star/plus/
  ordered-dot/ordered-paren spellings, disagreeing value, trailing prose,
  empty value (AC-3), one/two/three-space indentation in bare and list-item
  spellings, blockquote prefix, nested list items at 2 and 4 spaces with
  dash/plus/ordered markers (October indentation grammar).
- Exempt: clean document, fenced ``` block, tilde fence, four-space indented
  code block.
- Categories fire independently (AC-4): `banner-without-superseded-by` on an
  Accepted fixture, `banner-names-other-replacement` on a Superseded fixture,
  and `body-asserts-status-stays` for unqualified stays-prose.

Metric-v2 fail-closed proof against the production
`_require_metric_versions` and the real `require_metric_version`, 9/9:
candidate ledgers recording None/1/3 are rejected; trusted ledgers recording
v1/v3 fail through `require_metric_version`; nonempty (`known`), nonempty
(`details`), both, non-dict, and malformed `known` unversioned legacy ledgers
cannot migrate; only the structurally empty unversioned ledger transitions.
Matches the 16 provenance tests, including the six
`test_nonempty_or_malformed_unversioned_ledger_cannot_migrate` shapes.

Corpus evidence at this head: the diff vs the merge base removes exactly one
body `**Status:**` line from 93 documents under `docs/adr/` and `docs/specs/`
and re-adds none; the only other changed docs are the new ADR and its
ADR-INDEX row. CHANGELOG carries the literal `(#1532)` marker under
`### Changed` (line 610). The branch's footprint touches no `packages/` path
(docs, scripts, tests, quality, CHANGELOG only).

Hosted-CI note: at this exact head the live refresh shows 73 check runs
`cancelled` and 2 `failure` — the two failures are the umbrella aggregators
"SAST (bandit + semgrep + gitleaks)" and "Quality gate (Pillars 1–4, 7, 8)",
which died at 10s/8s with empty output and failed only in their "Require
every … to succeed" steps (`check_ci_job_results.py` over `needs:` children
that were all cancelled). No scanner, quality, or coverage finding exists;
the cancellation cascade is infrastructure. The repair is a CI requeue at
this head, which requires GitHub write access — recorded here as the handoff,
not performed.

Develop-tip note: `origin/develop` has moved three commits past the merge
base (05070ff07, 7714424b0, 5056cf069). A read-only `git merge-tree` probe
shows the only conflict is `CHANGELOG.md`; this round's recorded block was a
preflight `gh api` timeout plus the cancelled coverage gate, not a develop
sync conflict, so the head was not rewritten here. The integrator should
expect that one-file conflict at the next sync.
