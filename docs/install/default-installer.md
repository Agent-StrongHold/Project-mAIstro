# Default installer flow

`maistro-install` now models the curl-first default installer as a safe, functional plan rather than an opaque shell script. The intended remote entrypoint is a small fetcher that performs preflight checks, verifies the pinned installer payload, and hands off to the shared `InstallAnswersV1` resolver.

## Version selection (E5/#298)

`get.sh` and `get.ps1` install a **release tag**, not a branch. This is what
makes "install v1.0.0" expressible; it is also what makes two people running
the same command a week apart get the same code.

| Intent | POSIX | PowerShell |
|---|---|---|
| Latest release (default) | `./get.sh` | `.\get.ps1` |
| A specific release | `./get.sh --version v1.0.0` | `.\get.ps1 -Version v1.0.0` |
| A release candidate | `MAISTRO_VERSION=v1.0.0-rc1 ./get.sh` | `.\get.ps1 -Version v1.0.0-rc1` |
| Contributor / unreleased | `./get.sh --channel dev` | `.\get.ps1 -Channel dev` |
| A specific branch | `./get.sh --branch my/topic` | `.\get.ps1 -Branch my/topic` |

The latest release is resolved from the GitHub API's `/releases/latest`, which
**excludes prereleases**: an rc has to be asked for by name and is never handed
to someone who just ran the one-liner.

**When no release exists yet** — the state the repository is in today — the
default install prints a four-line warning naming the fallback, then installs
the `main` branch, which is the only branch a final release tag may point at
([ADR-073126-c4e1](../adr/ADR-073126-c4e1-release-and-versioning-process.md) §2).
The same fallback covers an unreachable or rate-limited API. Pass
`--require-release` / `-RequireRelease` (or set `MAISTRO_REQUIRE_RELEASE=1`) to
turn that fallback into a hard failure, which is what CI and any reproducible
install should do.

Image tags follow the source tree: a tagged install exports
`MAISTRO_IMAGE_TAG=vX.Y.Z`, so the `image_pull` compose the wizard generates
pins `ghcr.io/agent-stronghold/{maistro-engine,hive-conductor}:vX.Y.Z` rather
than `:latest`. A branch install uses `latest`, and `install.sh` run directly
out of a tree derives the tag from `git describe --tags --exact-match`.

## Preflight

The plan includes a best-effort `environment` report with:

- OS, distro, WSL status, and architecture.
- Admin/root availability and a user-scoped fallback hint.
- Docker and Podman command/daemon probes.
- KVM device and Hyper-V/WSL hints for sandbox and VM choices.

## Safe defaults

Defaults are intentionally conservative:

- `install_surface: curl` documents the curl bootstrap path.
- `delivery_mode: image_pull` is the fast default; `source_build` pulls source and builds locally with the same answers/runtime parameters, so the user-visible behavior should only differ by install time.
- `sandbox_profile: safe` denies docker socket mounts and marks the reactor preview read-only. The `developer` profile still keeps the installer security posture: no privileged containers, no docker.sock, no-new-privileges, and dropped Linux capabilities. Host-privileged unsafe installs are not supported by the installer; users who need unsupported options should build from source.
- `crypto_profile: distributed_identity_root` creates the default distributed identity/trust root for signing, auditability, approvals, and federation without enabling wallet/spending plugins.
- `reactor_enabled: true` seeds the first guide/operator/builder agents.
- `admin_user` and `daily_driver_user` are rendered into the generated bootstrap user list.
- Secrets stay out of answers YAML; provider selections are intent flags only.

Operators may select the `developer` sandbox profile for local iteration, but `unsafe_host` is intentionally not in the schema or wizard; users who want unsupported options can build from source instead of using the default installer. Crypto choices are explicit: `distributed_identity_root` is default, `no_crypto` removes the identity root for constrained demos, and `full_all_crypto` is reserved for downstream installers that enable the complete DID/VC and wallet-capable surface behind policy gates.

## Generated outputs

The install plan exposes `generated_artifacts` for downstream curl/web installers to materialize:

- curl entrypoint text,
- install script phases,
- compose override preview for the reactor,
- delivery intent for image-pull vs source-build installation,
- sandbox policy showing host-privileged access and docker.sock mounts are disabled,
- identity-root materialization intent,
- unsupported-option handoff guidance that points source builders away from the default installer,
- bootstrap users,
- first agents,
- tutorial/setup todo list that advances the admin and daily-driver profiles once setup decisions are complete.

## What remains to make this actually work

The implementation now resolves a plan and can materialize local install artifacts. To ship the remote curl installer end to end, finish these pieces in order:

1. **Publish a real curl entrypoint.** The temporary curl URL is the GitHub Gist raw URL encoded in `DEFAULT_CURL_INSTALL_URL`; swap that constant to the production domain when DNS is ready. The hosted script must detect OS/arch, refuse unsupported platforms clearly, download a pinned release artifact, verify its checksum/signature, and then invoke `maistro-install`.
2. **Materialize plan artifacts.** Use `maistro-install --materialize-dir ./maistro-install-out` to write the selected answers file, delivery manifest, compose override, sandbox policy, first-users manifest, first-agents manifest, identity-root manifest, unsupported-option handoff, tutorial todo list, and local review script to the install target directory.
3. **Bootstrap distributed identity root.** Implement the default `distributed_identity_root` materializer so it creates or imports the local instance identity/trust root without enabling wallet or spending components. `no_crypto` must skip this materializer, while `full_all_crypto` must stay behind explicit downstream policy gates.
4. **Wire users and first agents to runtime code.** Connect `admin_user`, `daily_driver_user`, `additional_users`, `first_agents`, and `reactor_enabled` to the server/core bootstrap APIs instead of leaving them as plan metadata.
5. **Start the stack, not just build it.** Keep the safe default preview/build behavior, but add an explicit confirmed install mode that runs compose validation, builds/pulls required services, starts the selected profiles, and prints recovery/rollback commands.
6. **Persist setup progress.** Store the tutorial/setup todo list and profile-level decisions so the admin and daily-driver profiles can level up only after required setup choices are complete.
7. **Package and test release artifacts.** Add CI that builds the installer payload, signs/checksums it, runs curl-style smoke tests on Linux/macOS/WSL targets, and exercises Docker and Podman paths without requiring secrets.
8. **Document source-build escape hatch.** Keep unsupported host-privileged or experimental options out of the installer; document source-build steps for operators who intentionally need unsupported settings.

## Bare-machine to Hive Conductor chat checklist

To go from a machine with no Python, no container runtime, and no virtualization setup to a running Hive Conductor chat that can create an agent DAG autonomously, the installer still needs these executable pieces:

1. **Native bootstrapper with no Python dependency.** Provide POSIX shell and PowerShell entrypoints that run on a bare host, detect OS/arch, install or locate `uv`, and then fetch the pinned `maistro-install` payload.
   - The POSIX side (`get.sh` → `install.sh`) ships today; `install.sh` resolves `uv` itself rather than depending on it being preinstalled.
   - The Windows side now has a native PowerShell entrypoint too: `get.ps1` (repo root) enables WSL2, installs an Ubuntu distro (handling the feature-enable reboot via a RunOnce resume hook), then hands off into the distro and runs `get.sh`/`install.sh` there as root. It does not yet feed into the `maistro-install` wizard plan described above — it's wired directly to the existing shell installer.
2. **Privilege and runtime installer.** Detect whether elevation is available, then install or guide installation of Docker Engine/Podman on Linux, Docker Desktop/WSL2/Hyper-V on Windows, and Docker Desktop/Colima-compatible tooling on macOS. The script must verify the daemon is running before proceeding.
   - Done for macOS (`install.sh` offers Docker Desktop or Colima via Homebrew) and for apt-based Linux/WSL2 (`install.sh` offers Docker Engine via apt). `get.ps1` requests elevation only for the one step that needs it (enabling the WSL2/Virtual Machine Platform Windows features).
3. **Virtualization readiness.** On Windows, verify WSL2/Hyper-V prerequisites and reboot requirements; on Linux, verify KVM/cgroups where needed; on macOS, verify the selected container VM is started.
   - `get.ps1` checks the Windows build (WSL2 needs 19041+) and reads CPU virtualization-firmware state as an advisory check (BIOS/UEFI changes can't be made from a script). The reboot-and-resume path is handled via a `HKCU\...\RunOnce` entry, not yet via a Scheduled Task — acceptable for a single resume, but it only fires at the *next interactive logon*, not unattended.
4. **Delivery implementation.** For `image_pull`, pull pinned Hive Conductor and dependency images and pass the generated parameters. For `source_build`, clone the pinned source revision, run `uv sync --extra bootstrap`, build compose services locally, and pass the same generated parameters.
5. **Secrets and provider setup.** Prompt for provider/account intent, then collect actual API keys only through a secrets file or secure prompt that is never committed or written into answers YAML.
6. **Compose stack startup.** Generate final compose files, start Postgres/LiteLLM/Langfuse/Hive Conductor services, run migrations, and wait for health checks instead of stopping at compose validation/build.
7. **Identity and bootstrap users.** Materialize or import the distributed identity root, create the admin profile, create daily-driver user 1 and any additional users, and record recovery/setup actions.
8. **Reactor and first agents.** Start the reactor service with the chosen sandbox and crypto profiles, seed the first guide/operator/builder agents, and verify they can enqueue and complete a minimal DAG task.
9. **Hive Conductor chat readiness.** Open or print the Hive Conductor URL, verify login/session creation, verify chat can call the backend, and run a smoke prompt that creates a small agent DAG autonomously.
10. **Recovery, rollback, and logs.** Print exact commands for status, logs, restart, backup, teardown, and source-build escape hatch, and write them into the materialized install directory.
