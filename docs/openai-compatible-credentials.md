# OpenAI-Compatible Credentials

The Credentials page includes a generic `openai_compatible` provider for an
operator-owned OpenAI-shaped gateway. `display_name`, `base_url`, organization,
and project are non-secret configuration. The API key is written only through
the existing encrypted `UserCredentialStore`; list, edit, test, and discovery
responses never contain it.

## Precedence and conflicts

Environment configuration remains the deployment-wide default. A saved
OpenAI-compatible credential is a user-scoped provider binding and does not
rewrite `LITELLM_API_BASE`, `LITELLM_API_KEY`, or the environment's default
model. Connectivity tests and model discovery return the credential as a
canonical `model.chat` `Binding` (the same type the environment-configured
gateway path authorizes through), but no shipped consumer resolves a saved UI
credential into model invocation yet: Hive chat/voice still build their model
port from the environment, and wiring saved credentials into that path lands
with the canonical egress cutover tracked in #56/#1084 — this issue deliberately
does not add a second invocation authority for it (#448, Wave 0). Until such a
consumer exists, the environment gateway keeps precedence. If a UI credential
and environment gateway both exist, they are separate named providers rather
than an implicit merge: operators should select one binding, not expect API
keys or model catalogs to be combined.

Saving a base URL is an explicit endpoint decision. The exact origin is added
to the canonical outbound policy so a private enterprise gateway can be used;
HTTP(S) shape, credentials-in-URL, query, and fragment are rejected. Redirects
and every subsequent destination are still checked by the shared outbound
transport under the #67 policy. Deleting the credential removes its secret and
non-secret metadata; a disabled credential retains its encrypted key but is not
eligible for selection.

## Testing before save

`POST /v1/credentials/openai_compatible/test` accepts draft configuration and,
for a first connection, a draft key. It calls `/v1/models`, returns model IDs,
and persists nothing. Existing keys are used through the vault callback when
no draft key is supplied. Failures are categorized as `authentication`,
`connectivity`, `TLS`, `policy rejection`, or `incompatible API behavior`, so a
failed test cannot create a configuration that appears usable.
