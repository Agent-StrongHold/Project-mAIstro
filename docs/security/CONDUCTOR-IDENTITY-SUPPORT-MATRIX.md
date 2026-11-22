# Conductor identity support matrix

Status: supported in the shipped Conductor image.

The Conductor image uses CPython `3.13.15` and installs the engine's
`maistro-core[identity]` extra. Its native identity wheel contract is pinned to
`bip-utils==2.12.1`, `coincurve==21.0.0`, and `pynacl==1.6.2`. `coincurve`
21.0.0 publishes the Linux `cp313` wheels required by the image; Python 3.14
is not a supported Conductor image runtime until a compatible wheel set is
verified.

| Deployment | Identity contract | Health status | Supported behavior |
| --- | --- | --- | --- |
| Engine library with `maistro-core[identity]` | Caller supplies a supported Python and the identity extra | Importable and caller-owned | `ConductorSeed` and lifecycle APIs are available; the engine does not own setup or a product identity store |
| Conductor image (default) | CPython 3.13.15 plus the pinned wheel set | `operational` after crypto setup and seed/DID verification | Setup generates and vault-persists the seed, returns the one-time mnemonic, and records the DID; health decrypts and derives the seed before reporting operational, and a vault write failure returns 503 before accounts are created |
| Conductor image with crypto identity deselected | Same image, no seed provisioned | `disabled` | Normal Conductor auth/vault operation remains supported; DID/seed-dependent controls are not enabled |
| Conductor image with a missing or broken identity runtime | Not a shipped profile | `unavailable` or `misconfigured` | Setup refuses crypto identity before creating accounts, and the setup UI does not offer the failing action |

The image build runs an import-and-derive smoke test for identity. A build with
`INSTALL_OBSERVABILITY=1` additionally imports the advertised OpenTelemetry
extra. Release/security CI repeats the identity import and derivation inside
the built image, including the Python and distribution-version assertions.

Engine and Conductor are separate contracts: engine tests cover primitive and
lifecycle behavior, while Conductor tests cover setup atomicity and the live
health/UI deployment behavior. Neither deployment creates a second execution
or authorization authority.
