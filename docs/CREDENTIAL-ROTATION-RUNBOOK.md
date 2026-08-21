# Credential Rotation & Session Purge Runbook

Post-disclosure remediation for the Hive Conductor data directory.

**Related:** issue #281 (report) · PR #332 (the fix). #332 closed an
unauthenticated arbitrary file read: the SPA fallback route joined an
attacker-controlled path onto the static root without containment, so any file
readable by the server process was fetchable over HTTP with no credentials.
That included `credential_master.key`, `user_credentials.enc`, and `state.db`.

**#332 stops further reads. It does not un-disclose anything already read.**
This runbook is the second half: rotate the master key so the disclosed one is
worthless, and revoke every session so disclosed session ids stop resolving.

---

## When to run this

Run **both** procedures if any of the following is true:

- The deployment ran a build containing the #332 path-traversal bug and was
  reachable from an untrusted network.
- `credential_master.key`, `user_credentials.enc`, or `state.db` was copied,
  backed up, or logged anywhere you do not fully control.
- A backup, snapshot, or container image containing the data directory leaked.
- Anyone left the team who had filesystem access to the data directory.

Rotating the master key does **not** invalidate the third-party tokens stored
inside (Jira, GitHub, Airtable…). If the store contents were disclosed, those
tokens are compromised too — **revoke and reissue them at the provider**, then
have users re-enter them. Rotation protects the store going forward; it is not
a substitute for revoking leaked upstream tokens.

---

## Before you start

1. **Stop the Conductor.** Both procedures operate on files the running process
   holds open and caches in memory. A running Conductor will write stale state
   back over your work.
   ```bash
   docker compose stop hive-conductor      # or: systemctl stop hive-conductor
   ```
2. **Back up the data directory** (encrypted, off-box). Rotation is atomic and
   verified, but a backup costs nothing:
   ```bash
   tar czf ~/conductor-backup-$(date -u +%Y%m%dT%H%M%SZ).tgz -C "$CONDUCTOR_DATA_DIR" .
   ```
   Treat that tarball as compromised material: it contains the *old* key. Delete
   it once rotation is confirmed.
3. Know your data directory. It is `CONDUCTOR_DATA_DIR` from `backend/.env`
   (default `~/.conductor`). It contains:

   | File | What |
   |------|------|
   | `credential_master.key` | Fernet master key, mode `0600` |
   | `user_credentials.enc`  | Fernet-encrypted `{user: {provider: secret}}` |
   | `state.db`              | SQLite: sessions, missions, DAGs, audit log |

---

## 1. Rotate the credential master key

Both commands are **dry-run by default**. They print exactly what they would do
and change nothing until you add `--yes`.

```bash
# Dry run — see what would happen.
uv run maistro security rotate-credential-key --data-dir "$CONDUCTOR_DATA_DIR"

# Do it.
uv run maistro security rotate-credential-key --data-dir "$CONDUCTOR_DATA_DIR" --yes
```

Output:

```
Planned: credential master-key rotation
  data dir    : /home/hive/.conductor
  key file    : /home/hive/.conductor/credential_master.key
  store file  : /home/hive/.conductor/user_credentials.enc
  to re-encrypt: 7 secret(s) across 3 user(s)
  new key     : generated

Rotated. 7 secret(s) across 3 user(s) re-encrypted under the new key.
  new key written to: /home/hive/.conductor/credential_master.key
The previous master key is now useless. Restart the Conductor.
```

Options:

| Flag | Use |
|------|-----|
| `--yes` | Actually perform the rotation. Without it, dry run. |
| `--new-key <fernet-key>` | Rotate to a key you supply (e.g. one from your secret manager) instead of a generated one. |
| `--show-key` | Print the new key to stdout. Needed when the key lives in an env var — see below. |

If the current key cannot decrypt the store, the command **aborts and changes
nothing**. Fix that first (restore the right key file from backup) rather than
forcing anything.

### If `HIVE_CREDENTIALS_MASTER_KEY` is set in the environment

The env var takes precedence over the key file *when the store is constructed
directly*. Note that Hive Conductor's own startup path
(`services/user_credentials.init_credential_store` → `UserCredentialStore.open`)
always reads the **key file**, so for a stock Conductor the file is
authoritative and the env var is inert. If you set the env var anyway — or you
run another consumer of `maistro-core` that constructs `UserCredentialStore`
directly — the rotation will warn you, and you must update the variable
yourself:

```bash
# Capture the new key at rotation time.
uv run maistro security rotate-credential-key \
  --data-dir "$CONDUCTOR_DATA_DIR" --show-key --yes
```

Then either:

- **Preferred:** unset `HIVE_CREDENTIALS_MASTER_KEY` everywhere (compose files,
  systemd unit, `.env`, CI secrets) and let the `0600` key file be the single
  source of truth; or
- Update `HIVE_CREDENTIALS_MASTER_KEY` to the printed value in *every* place it
  is set, before restarting.

Getting this wrong means the service starts and then fails to decrypt the store
(`CredentialStoreUnavailable`). Nothing is lost — the key file still holds the
correct key — but integrations break until the variable is fixed.

### If rotation is interrupted

Rotation swaps the ciphertext first and the key file second, with the new key
already durably staged at `credential_master.key.new`. If the process is killed
between those two renames, the live key file is stale but the key that reads the
live ciphertext is on disk. Nothing is lost, and the next
`UserCredentialStore.open()` — i.e. the next Conductor start, or simply
re-running the rotate command — completes the swap automatically and logs
`credential_rotation_repaired`.

If you see `credential_rotation_unrecoverable` in the logs, **stop**: neither
key decrypts the store. Restore the data directory from backup and re-run.

---

## 2. Purge all sessions

Session ids are bearer tokens: anyone who read `state.db` can present one and be
that user. Rotation does not touch them.

```bash
# Dry run.
uv run maistro security purge-sessions --data-dir "$CONDUCTOR_DATA_DIR"

# Do it.
uv run maistro security purge-sessions --data-dir "$CONDUCTOR_DATA_DIR" --yes
```

Output:

```
Planned: session purge
  state db : /home/hive/.conductor/state.db
  store    : sessions
  to revoke: 12 session(s)

Revoked 12 session(s). Every user must log in again.
```

Use `--state-db <path>` if `CONDUCTOR_STATE_DB` points somewhere other than
`<data-dir>/state.db`.

If there is no state DB the command says so and exits cleanly: sessions were
in-memory only, and restarting the Conductor already cleared them.

**Every user must re-authenticate afterwards.** Their browsers still hold a
`hive_session` cookie, but it no longer resolves — `/v1/auth/whoami` returns
`{"authenticated": false}` and they are bounced to the login screen. Elevation
grants (`elevated_grants`) live inside the session records and are revoked with
them, so any in-flight privileged task must be re-elevated. Tell users before
you run it.

In-process equivalent (for an admin route or a maintenance hook, not the CLI):

```python
import stores
revoked = stores.purge_all_sessions()
```

---

## 3. Restart and verify

```bash
docker compose start hive-conductor
```

Check:

1. Logs contain `user_credential_store_ready` and **no**
   `user_credential_store_unavailable`.
2. `GET /v1/credentials` (as a logged-in user) still lists their configured
   providers — proof the re-encrypted store decrypts.
3. An old session cookie gets `{"authenticated": false}` from
   `GET /v1/auth/whoami`.
4. Delete the pre-rotation backup tarball; it contains the compromised key.

---

## What this does not cover

- **Third-party tokens.** Revoke and reissue at the provider (see above).
- **The admin/user privilege keys** (`maistro.privilege`, SPEC-012). Those are
  separate; `rotate_admin_key` in `packages/maistro-core/src/maistro/privilege.py`
  handles them.
- **The age-encrypted vault** (`maistro.vault`, SPEC-011). Separate key
  material; rotate per its own procedure.
- **B2B service keys** (`maistro.auth`). Reissue from the auth store if the
  deployment uses them.

---

## Where the code lives

| Piece | Path |
|-------|------|
| `rotate_master_key`, `repair_interrupted_rotation` | `packages/maistro-core/src/maistro/credentials/store.py` |
| `maistro security` CLI | `packages/maistro-core/src/maistro/cli/_security.py` |
| `purge_all_sessions` | `packages/hive-conductor/backend/stores.py` |
| `JsonStore.clear` | `packages/hive-conductor/backend/services/model_store.py` |
| Tests | `packages/maistro-core/tests/credentials/test_master_key_rotation.py`, `packages/maistro-core/tests/cli/test_security.py`, `packages/hive-conductor/backend/tests/test_session_purge.py` |
