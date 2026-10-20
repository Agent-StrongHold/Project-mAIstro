---
inventory-delta:
  packages/maistro-core/tests: +3
---
# auto-975 — public-surface union pin for `maistro.extensions`

M9-H3 (#975) repair round. This round's develop sync (two merges: `9bd1a93ee`
then `origin/develop` at `28614700b`) unioned
`packages/maistro-core/src/maistro/extensions/__init__.py` between the
certification lane's `Certification*` exports and develop's compat/sandbox
exports. The first union resolution silently dropped the nine
`Certification*` names from `__all__` (ruff F401 caught it only because the
root also imports those names; a name imported nowhere else would have
vanished without a trace). The suite-inventory gate cannot see this failure
class — it counts tests, not exports — so the surface is now pinned
structurally.

`packages/maistro-core/tests/extensions/test_public_surface_union.py` (+3):

- `test_every_submodule_import_is_published_in_all` — every name the package
  root binds through `from maistro.extensions.* import ...` must appear in
  `__all__`; a star import or a dropped re-export fails by name;
- `test_every_published_name_resolves` — every `__all__` entry is
  `getattr`-able on the package (no published-but-unresolvable name);
- `test_both_merged_halves_are_exported` — the two unioned families (the
  #975 certification surface: report/seal/profile/certify/verify/
  trust-claim; the #955 compat surface: verdict/metadata/negotiate/parse)
  are both published.

Regression-naming proof: with `CertificationReport` and `negotiate` removed
from `__all__` (the exact merge-resolution failure shape), the first and
third tests fail naming the missing entries; with the tree restored, all
three pass. No existing test was removed, renamed, or moved.
