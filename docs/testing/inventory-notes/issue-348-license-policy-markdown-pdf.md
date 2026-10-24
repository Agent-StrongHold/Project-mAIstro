---
inventory-delta:
  tests/: +1
---
# issue-348-license-policy-markdown-pdf

One added test, no removals, nothing renamed or moved.

`tests/test_check_license_inventory.py::test_shipped_policy_resolves_the_research_image_markdown_pdf_dependency`
pins the reviewed resolution row `pkg:pypi/markdown-pdf@*` in
`quality/license-policy.json` and runs the exact CI failure shape (purl
`pkg:pypi/markdown-pdf@1.5` with a `?package-id=` bom-ref, no license
evidence) through the real `_component_record` classification path. The
hosted `Container scan + SBOM + cosign` job failed at head `a1faf9aa`
because the research image SBOM carried that component with no license
metadata; the row (MIT, from the wheel's
`License :: OSI Approved :: MIT License` classifier — same evidence shape
as the existing `markdown-it-py` and `aiosqlite` rows) is the gate's own
required resolution, not a gate weakening.

The row-pinning matters because `quality/*.json` files merge cleanly
while losing rows: the test fails if a future merge silently drops the
resolution, which would re-break the hosted gate.

No production code changed. `quality/license-policy.json` is the other
path touched.
