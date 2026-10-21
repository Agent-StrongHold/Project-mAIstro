# Issue 848: CI repair — devskim DS137138 on the Rovo endpoint predicate docstring

Repair round at head `150cb0593`. No test counts moved in this round (the fix
is a docstring and a comment in one shipped file; the behavioural coverage was
added by the earlier rounds), so this note carries no `inventory-delta:` block.

## The failure, as the CI evidence states it

The merge-queue evaluation recorded exactly one red gate at `150cb0593`:

- `devskim` check-run `118998153077` — **failure**, app
  `github-advanced-security`, output title **"2 new alerts"**, summary "New
  alerts in code changed by this pull request ... 2 warnings", with the
  branch-alert link `?query=pr:2147+tool:devskim+is:open`.

The two annotations are inline on the PR (#2147) and name the file and lines
exactly:

| Location | Rule | Text |
| --- | --- | --- |
| `packages/hive-conductor/backend/services/mcp_defaults.py:86` | DS137138 (Insecure URL) | "An HTTP-based URL without TLS was detected." |
| `packages/hive-conductor/backend/services/mcp_defaults.py:88` | DS137138 (Insecure URL) | "An HTTP-based URL without TLS was detected." |

Both lines are inside the `is_atlassian_rovo_url` docstring this branch
rewrote (the PR's own prose, spelling out the counter-examples the predicate
refuses). The sibling `DevSkim` job (the Actions workflow) **succeeded** — the
scan ran; it is the SARIF upload that produced the two *new* alerts, because
the PR introduced them.

## Reproduction with the action's own engine

`microsoft/DevSkim-Action@v1` installs `Microsoft.CST.DevSkim.CLI` from
NuGet; the same tool is available locally (`devskim 1.0.90+fb2d676ce4`).
Running it over the *pre-change* file reproduces the annotations at the same
lines and columns:

```console
$ devskim analyze -I packages/hive-conductor/backend/services/mcp_defaults.py -f text
packages/hive-conductor/backend/services/mcp_defaults.py:86:59:86:68 [Moderate] DS137138 Insecure URL
packages/hive-conductor/backend/services/mcp_defaults.py:88:36:88:65 [Moderate] DS137138 Insecure URL
```

A whole-tree comparison of the PR base (`252950bdb`) against the candidate
(`150cb0593`), with the DevSkim workflow's own `ignore-globs` applied to the
results, shows that these are the **only** new alerts the PR introduces:
738 post-glob findings at the base become 740 at the candidate, and the two
extra rows are exactly the DS137138 pair above — nothing else moved in either
direction. (The raw, unfiltered counts are 1850 → 1854; the workflow's
`**/tests/**` glob is what removes the branch's own test-file findings, so
the gate only ever saw the two rows in the shipped module.)

## Root cause

DS137138 matches the pattern `http://[^/^\s^"]+` in **code** scope. A
docstring is a string literal in the source, so it is code scope, and the two
URLs written in the prose were matched as if they were endpoints. Empirically
(DevSkim 1.0.90, same engine):

| Where the URL literal sits | Flagged? |
| --- | --- |
| `X = "http://example.com/a"` (code) | yes |
| `# http://example.com/b` (comment) | no — comments are out of the rule's scope |
| `Y = 1  # http://example.com/c` (suffix comment) | no |
| `"""docstring http://example.com/d"""` (docstring) | **yes** |

A same-line suppression *is* honoured inside a docstring (DevSkim matches the
magic phrase on the flagged physical line whatever its scope), but that phrase
would then render in the public docstring of a shipped module, and this
repository has no precedent for a scanner marker inside shipped
documentation — every existing DS137138 disposition is a dated suffix on a
code line. The fix therefore removes the literal from the prose instead of
adding a marker to it.

## The fix

`packages/hive-conductor/backend/services/mcp_defaults.py`:

- The `is_atlassian_rovo_url` docstring keeps the same statement of the rule
  — hostname-based, never substring, transport-checked, plaintext scheme and
  non-standard port refused even for the genuine host — with the refused
  counter-examples named in prose ("a plaintext scheme (anything but
  ``https``)", "an odd port") rather than written as URLs.
- A comment above the function points at the file that carries the concrete
  counter-examples (`backend/tests/test_mcp_trust_boundary.py`, which the
  scan's `**/tests/**` glob excludes) and records why the docstring does not
  spell them out, so the next maintainer does not "helpfully" restore the
  literal and re-break the gate.

No behaviour changed: `is_atlassian_rovo_url` still refuses a non-`https`
scheme and any port other than 443, and the tests that pin it
(`test_plaintext_and_nonstandard_port_endpoints_are_refused`,
`test_mcp_defaults_and_manifest.py`) are untouched.

## Validation

- `devskim analyze` (1.0.90) on the fixed file → **zero DS137138**; the only
  remaining finding is the pre-existing DS162092 at line 19 (the unchanged
  `FILESYSTEM_MCP_URL` loopback default), which this PR does not touch and
  which therefore raises no new alert.
- Whole-tree comparison, PR base vs the fixed candidate, with the workflow's
  ignore-globs applied → **0 new alerts**. The gate-relevant (post-glob)
  counts are 738 (base `252950bdb`) → 740 (candidate `150cb0593`, the two
  DS137138 rows) → 738 (fixed candidate): the delta that produced the red
  gate is gone, and nothing else moved in either direction. The *raw* scan
  counts differ (1850 / 1854 / 1852) only because the branch's own test
  files add findings that the workflow's `**/tests/**` glob excludes — those
  never reach the gate.
- `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .`
  → "3389 files already formatted".
- `uv run pytest packages/maistro-core/tests/harness/test_importers.py
  packages/maistro-core/tests/security/test_trust_monotonic.py -q -x` → 44
  passed.
- `.venv/bin/python -m pytest
  packages/hive-conductor/backend/tests/test_mcp_defaults_and_manifest.py
  packages/hive-conductor/backend/tests/test_mcp_trust_boundary.py -q -x` → 33
  passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` → ok, 3883 node IDs;
  `--suite packages/maistro-core/tests` → ok, 16952 node IDs.
- CI-repair ledger gate, run with CI's exact arguments:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, **1324 reviewed
  identities → 1324 findings**, 0 unclassified, 0 never-allowlist. This round
  eliminates no identity and adds none, so `quality/vulture-baseline.json`
  is unchanged (no amendment was needed).
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → exit 0 (358 contract-marker gaps
  unchanged, 1 enumeration gap, 0 lifecycle violations).

## Not actionable in this tree

The lane brief also carried a previous block: *"recovery budget exhausted:
provider error (gemini/gemini-3-flash-preview): 400 ... Unknown name
\"store\""*. That is the evaluation harness's inference provider rejecting a
tool-schema field named `store` — an infrastructure/provider fault on the
reviewing side, with no repository artefact behind it. Nothing in this tree
produces or consumes that schema, so there is no in-repo repair for it; the
next evaluation attempt with a working provider is what clears it.
