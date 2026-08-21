---
id: SPEC-011
title: "Secrets vault — age-encrypted file unlocked by admin keypair"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-028
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-011: Secrets Vault

See `blakematthews-dev/project_maistro` specs/security/S-141-vault.md for full spec.

## Acceptance Criteria

- [ ] `secrets.use(name, callback)` is the ONLY public API; `secrets.get` does not exist anywhere in the codebase
- [ ] CI grep for `secrets.get` outside test fixtures fails the build
- [ ] Vault file `secrets.age` is encrypted to the admin's `m/0'` public key from the Conductor Seed
- [ ] Admin private key is held in OS keychain on desktop, passphrase-encrypted file on headless Linux; never on disk in cleartext
- [ ] At startup, vault is decrypted into mlock'd process memory; private key zeroed after decryption; in-memory state zeroed on process death
- [ ] Vault unavailability at startup: if the admin private key cannot be retrieved from the OS keychain AND the passphrase-encrypted fallback file is absent or fails to decrypt, conductor refuses to start with a `VAULT_UNAVAILABLE` error and clear recovery instructions; conductor never starts with an empty or partial vault — fail-closed is the only acceptable behavior
- [ ] Bouncer rejects agent output containing any vault-credential prefix (final-line defense); the match pattern is the first 8 bytes (64 bits) of the SHA-256 hash of each credential value; prefix length is fixed and documented in the Bouncer implementation
- [ ] Bouncer pattern set is regenerated within 100ms of any vault mutation (add, rotate, remove, rebuild)
- [ ] All vault mutations are admin-signed and recorded as VCs in the audit log
- [ ] No credential value is ever in a Langfuse trace, log line, or panic stack
- [ ] Setup wizard asks about vault backup; operator must explicitly acknowledge "no backup" to skip
