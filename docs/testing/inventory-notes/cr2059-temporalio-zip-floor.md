---
inventory-delta:
  tests/: +6
---

# cr2059-temporalio-zip-floor

Repair round for #2059 on `fix/vulture-single-owner-1357`.

The earlier `cr2059-container-scan-trivy-repair` note left the
`maistro-rsi-runner` Trivy findings against the `temporalio` wheel's shipped
Rust `zip` crate unresolved: CVE-2026-115905 (CRITICAL) and
CVE-2026-115907/08/09 (HIGH). The vulnerable code is not in a pip-installed
Python package but in the compiled `temporal_sdk_bridge.abi3.so` that the
wheel bundles, with matching `Cargo.lock` and linked crate paths for `zip`
8.6.0.

Fix: raise the `temporalio` floor from `>=1.27.0` to `>=1.35.0`. Version
1.35.0 is the first published release whose wheel bundles a Rust bridge built
against `zip` 9.1.2, which clears every fixed version for the four advisories
(`9.0.0` for three, `9.0.5` for one). `uv lock` resolved to `1.36.1` and
updated the `nexus-rpc` transitive pin from `1.4.0` to `1.5.0`.

New test: `tests/test_temporalio_bridge_zip_floor.py` (+6). It asserts the
declared floor, the locked version, the installed wheel's
`bridge/Cargo.lock`, and the compiled `bridge/temporal_sdk_bridge*.so` all
name only non-vulnerable `zip` versions. Negative controls reject the 1.34.0
manifest/binary state and refuse to match unrelated crates such as `gzip`.
Verified: the test fails on the pre-fix floor/lock for the intended reason
and passes after the lock update, without requiring an image build or
network call.

Local proof: `uv lock --check` exit 0; targeted pytest exit 0; Ruff lint and
format clean. The Vulture exact-debt-ledger gate remains green with the
updated environment.
