# Registration policy

Hive Conductor registration is **closed by default** after first-run setup. The unauthenticated `/v1/setup/complete` endpoint remains the only bootstrap path for the initial admin and daily-user accounts, and it is serialized so concurrent first-run requests cannot both provision owners.

The active public policy is visible at `GET /v1/setup/registration-policy`. Its response intentionally exposes only the policy mode (`closed` or `open`), not account counts, usernames, invitation state, or whether a specific account exists.

Administrators can explicitly change policy with `PUT /v1/settings/registration-policy` using `{"mode":"open"}` or `{"mode":"closed"}`. This endpoint sits under the existing protected settings namespace and therefore requires the same authenticated `config.write` authorization as other settings mutations.

For narrower access, administrators can create a time-bounded one-time invitation with `POST /v1/settings/registration-invitations`. The plaintext token is returned only in that response. Persistent state stores only a SHA-256-derived token key and expiry metadata. Invitation links use `?invite=<token>` on the login page; a successful registration consumes the invitation before account creation can race another request. A validation failure restores the still-valid claim so correcting a malformed signup does not waste the invitation.

Missing, malformed, expired, or unreadable registration-policy state fails closed. Policy and invitations use the same durable JSON store as the first-run setup marker, so a process restart does not silently reopen signup.
