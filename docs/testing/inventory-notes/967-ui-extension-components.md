---
inventory-delta:
  packages/maistro-core/tests: +73
---
# 967 — Governed UI/A2UI extension components projecting canonical state (M9-F2)

Adds the governed UI extension component contract
(`packages/maistro-core/src/maistro/extensions/ui.py`, exported from
`maistro.extensions`) and the suite that pins the issue's acceptance criteria
against reachable behavior.

## packages/maistro-core/tests (+66)

- `extensions/test_ui_components.py` (66 cases) — one test per rule, each
  naming the acceptance criterion it pins:
  - **AC-1 (render canonical state without direct DB/store access)**: the
    load-bearing one is `test_out_of_tree_manifest_projects_only_declared_
    canonical_fields` — an out-of-tree extension is manifest *bytes alone*
    (nothing to import, no store handle anywhere in the flow), and the
    projection carries exactly the declared binding fields from the
    host-supplied snapshot while canonical internals (actor principal, graph
    snapshot definition) never surface. Also pinned: bindings outside the
    closed `BINDABLE_FIELDS` allowlist and non-canonical kinds fail
    inspection; unprojected kinds render `None`; a structural test proves
    the contract module has no store/session/engine surface; model objects
    and plain snapshot dicts project alike (enum values normalized).
  - **AC-2 (mutating actions call governed seams; no local completion)**:
    a mutating action must name its governed route *exactly*; the
    `complete` intent and any `.../complete` route are not expressible (the
    closed `GOVERNED_ROUTES` table has no completion seam on purpose —
    pinned both negatively and by inspecting the table); dispatch resolves
    the canonical cancel seam from the canonical snapshot, HITL actions
    resolve run *and* node targets, `start_task` needs no canonical params,
    and local actions cannot carry routes or permissions.
  - **AC-3 (disabled/unauthorized enforced server-side, not merely hidden)**:
    a disabled extension's dispatch raises even though rendered metadata is
    the only thing a client could forge; missing principal permission,
    authority beyond the extension's governed grant, a terminal run status
    failing the `run_cancellable` precondition, and an unresolvable
    canonical target are each enforced at `dispatch` — the same evaluation
    that rendered the preview.
  - **AC-4 (component state loss/reload does not alter canonical state)**:
    client arguments carrying canonical field or binding names are refused
    (`ClientStateRejected`); a reload re-renders identically from the same
    snapshot and the host's snapshot is byte-identical after a refused
    smuggle attempt.
  - **AC-5 (no unrestricted scripts/network outside declared policy)**:
    nine injection vectors (script/iframe/object/embed tags, `javascript:`
    and `data:text/html` URIs, `eval(`, inline handlers, `srcdoc`) fail
    inspection; unsafe CSP tokens (`'unsafe-inline'`, `'unsafe-eval'`,
    wildcards, `data:`/`blob:`, plaintext HTTP, scheme-relative) are
    refused; `script_src` is required rather than inherited; `open_url`
    targets must fall inside the declared origin allowlist (plaintext,
    undeclared hosts, wrong schemes and `javascript:` each refused, while
    declared-origin targets with paths are accepted); rendered metadata
    carries the header-ready CSP.
  - **AC-6 (provenance inspectable in rendered metadata)**: every render
    and every dispatched call carries catalog id, component id, version,
    publisher and the manifest SHA-256; snapshot tampering is detected at
    every use; versioned assets are digest-pinned (`verify_component_asset`)
    and asset paths cannot escape the bundle.
  - Plus inspection hardening (unknown keys/versions, bad semver,
    duplicate ids/bindings/actions, unknown sandbox directives and action
    keys, malformed JSON) and lookup errors (unknown catalog/component/
    action fail with distinct types; catalogs register only under the
    extension id that shipped them; local actions dispatch nothing).

## Repair round on top of the PR head (+6, all in the same file)

Three follow-up fixes after the PR head (905f23db) hardened the contract and
each pinned the fix with tests that the original +66 did not include. Recorded
here so the ledger matches the reachable tree (collected: 72, not 66):

- `test_mutating_action_permissions_are_canonical_not_catalog_chosen` —
  AC-2: a governed route's required permissions are fixed by the platform;
  the catalog cannot swap in a low-authority token (or add one alongside).
- `test_component_required_permissions_are_enforced_at_dispatch` — AC-3:
  component-level `required_permissions` gate dispatch, not just render
  visibility.
- `test_replace_cannot_smuggle_fields_past_the_anchor` — AC-6: a
  `dataclasses.replace` of parsed fields with byte-identical raw bytes fails
  the snapshot integrity check.
- `test_scoped_state_keeps_installs_isolated_per_scope` — AC-3/AC-6: the same
  extension active in two scopes carries its own catalog and grant per
  (scope, extension_id); an org-scope grant does not authorize a
  workspace-scope mutation and provenance reflects each scope's manifest.
- Two more `test_unsafe_csp_tokens_are_rejected` cases (10 → 12): a CSP value
  smuggling `'unsafe-inline'` through `connect_src`, and a comma-joined
  multi-origin `connect_src` (header-injection smuggling) is refused.

## Develop-sync repair round (+1)

The develop merge brought the #981 lifecycle-proof boundary
(`stage_canonical_truth_untouched`): no module under `maistro/extensions/`
may hold an import line into `maistro.runs` / `maistro.goals` /
`maistro.graph`. `ui.py` imported the canonical status vocabulary to derive
`_CANCELLABLE_RUN_STATUSES`, tripping that check. The repair keeps both
contracts: the cancellable set becomes a projection-local literal (the
module's established pattern — `BINDABLE_FIELDS` and `GOVERNED_ROUTES` are
already closed literal tables), and anti-drift moves from an import edge to
the test suite:

- `test_cancellable_vocabulary_matches_canonical_run_lifecycle` — exact set
  equality between `ui_module._CANCELLABLE_RUN_STATUSES` and
  `{status.value for status in RunStatus} - TERMINAL_RUN_STATUSES` from
  `maistro.runs.model`; a canonical RunStatus change fails here until the
  same reviewed core change updates both sides.
