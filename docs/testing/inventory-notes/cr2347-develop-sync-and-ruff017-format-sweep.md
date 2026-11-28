---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/maistro-canvas/tests: +0
---

# cr2347 develop sync + ruff 0.17.2 markdown-format sweep

Repair/verification round for PR #2347 (bump ruff 0.15.12 -> 0.17.2) on
`dependabot/uv/ruff-0.17.1`. Starting head `ad75b3f990a4` carried an
uncommitted in-progress merge of `origin/develop` (`90002c42d37d`) with one
unresolved conflict (CHANGELOG.md, diff3-style, both hunks empty on the
branch side because the rebuilt branch had already dropped the base-era
entries). Resolution took the develop side for both hunks after verifying
none of develop's new entries (#1629/#2316/#2320/#2322/#2323/#2309/#1822/
#2356/#2375, GHAS plumbing) existed anywhere in the branch's CHANGELOG —
union without duplication. Merge committed as `0f786eef1d`.

ruff 0.17.2 formats python code blocks inside markdown, so the merge's two
new ADRs (ADR-041 canvas layer taxonomy, ADR-101826 WebAuthn adapter) failed
`uv run ruff format --check .` (CI exact args, ci.yml:113 / quality.yml:874).
Both files are pure develop additions, unclaimed by any test; formatted the
embedded code blocks only (`702ebaf871`, 56+/28-, prose untouched).

No tests added or removed; suite inventory `scripts/check-suite-inventory.py`
re-run against the merged tree: 21/21 suites match the recorded inventory.

Evidence run on the merged head (702ebaf871), all CI-exact invocations:
uv lock --check; ruff check .; ruff format --check .; vulture ledger
1220=1220 (base 90002c42); radon 124=124; xenon 124<=124 avg 0 modules 0;
interrogate 13/13 floors; release-consistency; merge-markers; public-routes;
route-permissions; reachability 82 + dispositions; promotion-surface;
image-inventory; image-pins; workflow-inventory; backlog-consistency;
execution-lifecycles 19/19; mypy --strict maistro-core/src 847 files clean
(after `uv sync --locked --all-extras` + editable maistro-evolve, matching
the quality-mypy job); formal/models --hypothesis-seed=0 vs live pg18
(migrations 068->070 applied): 670 passed; devskim scope + governed-llm
81 passed; gate self-checks (diff-coverage/gates-ran/vulture/suite-inventory)
192 passed; maistro-server + maistro-canvas 1413 passed; maistro-core full
suite 18668 passed after clearing a pre-existing `engine-042` residue row
(planted 2026-11-25T23:10:06Z by the prior attempt's run; the backlog
roundtrip test uses a fixed global item_id and has no cleanup — the failure
predates this round and reproduces on any tree against the polluted DB).
