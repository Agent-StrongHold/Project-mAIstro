---
inventory-delta:
  packages/maistro-ext-sdk/tests: +26
---
# Issue 949 repair: manifest-contract hardening for every parse entry point

Follow-up hardening of the M9-A1 manifest contract, driven by the gaps the
repair review surfaced. `packages/maistro-ext-sdk/tests` goes 83 → 109
collected node IDs; this note carries the +26 delta against the previous
note (`949-ext-sdk-package.md`).

## What moved the count

- `test_manifest_contract.py` (+24):
  - strict SemVer 2.0.0 grammar for `version` — leading zeros, empty and
    zero-padded numeric prerelease identifiers, and empty build metadata are
    rejected by name; the spec's own valid examples still parse (+14,
    parametrized 6 invalid + 8 valid);
  - a well-formed but unsupported `contract` range now fails through every
    parse entry point (`manifest_from_dict`, `manifest_from_json`,
    `manifest_from_yaml`), not only the directory front door (+3,
    parametrized per entry point);
  - duplicate object keys are rejected in JSON (top level and nested) and in
    YAML mappings rather than silently resolved last-wins — last-wins let a
    manifest show security review one authority set and validate against
    another (+4);
  - invalid-UTF-8 `bytes` input and an unreadably-encoded `extension.json`
    on disk surface as the single public `ExtensionManifestError` (+2).
- `test_out_of_tree_validation.py` (+2): entrypoint resolution mirrors
  importlib's FileFinder order — a package directory shadows a same-named
  module file, and a parent plain-module makes a deeper dotted path
  unimportable rather than validating against a file the host could never
  load.

## Why the SDK contract check moved

`validate_manifest` now enforces contract-range compatibility
(`_validate_contract_field`), so `manifest_from_dict` and the YAML front door
reject a `contract` that excludes `contract_version()` exactly like
`validate_extension_dir` always did. The check is a helper rather than
inline branches so the pipeline function stays at xenon rank B (the
per-function complexity ratchet counts it; the committed tree carried the
same 145-block ledger and this keeps it there).

## Mutant check

Negating the duplicate-key hook in `manifest_from_json`
(`object_pairs_hook=None`) fails `TestDuplicateKeysRejected` outright;
widening `_SEMVER_RE` back to `\d+\.\d+\.\d+...` fails the invalid-semver
parametrization; deleting the `targets_contract` raise inside
`_validate_contract_field` fails
`test_unsupported_contract_range_rejected_by_every_entrypoint`.
