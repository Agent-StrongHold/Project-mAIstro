---
inventory-delta:
  packages/maistro-turing/backend/tests: +21
---

# Issue #858 — Remove Turing's default service credential; require explicit governed service identity

The Turing backend previously failed closed on an unset `TURING_SERVICE_KEY`
(#1249/#1253), but the surrounding governance criteria were unproven. This
change closes them on the production activation path
(`packages/maistro-turing/backend/`):

- `config.py`: the key comes only from `TURING_SERVICE_KEY` or the
  `TURING_SERVICE_KEY_FILE` secret file (rotation/revocation without source or
  image change); blank/absent values raise and leave Turing unstartable. The
  identity's scopes are expanded through the canonical `maistro.auth` model
  and pinned at startup to the middleware's `TURING_INTERNAL_SCOPES` route
  allowlist — drift fails startup instead of widening the identity.
- `routes/health.py`: `/health/ready` reports the identity state; a degenerate
  registry answers 503 `unavailable` (reason names configuration, never key
  material).
- `provision.py` (new): opt-in `python -m backend.provision` bootstrap that
  generates a unique key (`maistro.security.secure_random`), prints it, and
  optionally stores it in a 0600 dotenv file; existing entries rotate only
  with `--force`.

Tests (`+21` node IDs):

- `test_service_identity.py` (9): source ratchet proving the retired
  `sk-svc-turing-dev-internal` literal exists nowhere in the activation
  package; configured-key-only authentication; canonical scope mapping with no
  admin/dashboard authority; startup refusal to mint a wider identity; blank/
  absent key refusal; secret-file rotation + revocation; env-over-file
  precedence; missing/empty secret-file refusal; `service_identity_status`
  unconfigured/drifted cases.
- `test_provision.py` (10): key uniqueness/prefix; never a known shared value;
  opt-in 0600 env-file storage with printed key == stored key; explicit
  `--force` rotation; unrelated env lines and trailing-blank handling; an
  unwritable env-file location exits 2; the plain print path; the `__main__`
  guard.
- `test_auth.py` (+3): `/health/ready` reports the configured identity and
  503 `unavailable` for a degenerate registry; the retired default credential
  is rejected over the wire (header and Bearer).
