---
inventory-delta:
  tests/: +3
---

# 1820: the elevation denial becomes a recoverable prerequisite report, and the retry contract gets a test

The runtime-selection half of #1820 was already covered by
`tests/test_install_runtime_selection.py`. The repair round closed the two
claims the lane's transcripts could not cover, and both are now tests in the
same file.

**Finding A — a denied elevation was not reported recoverably.** The Linux
bootstrap installs Docker Engine with `sudo apt-get update` /
`sudo apt-get install`, and both calls were unguarded. On a host that
denies the elevation the installer died on sudo's own error line: no
statement of what the one-time administrator step is, and no statement that
re-running the installer resumes the install. `bootstrap_apt_docker_runtime`
now checks for `sudo` before it mutates anything and reports a missing or
refused elevation as a prerequisite — the exact administrator command
(`apt-get update && apt-get install -y docker.io docker-compose-plugin`) and
the instruction to re-run `./install.sh`. The unsupervised daemon's log also
moved off `/var/log/dockerd.log`, which an ordinary account cannot create,
onto the install's own state directory.

Two node IDs: `test_denied_elevation_reports_a_recoverable_prerequisite`
(a host that has `apt-get` and refuses the elevation) and
`test_missing_sudo_reports_a_recoverable_prerequisite` (a host with no
`sudo` at all). Both fail against the pre-repair `install.sh` — the run
there dies on `sudo: command not found` or on sudo's raw error — and pass
after it.

**Finding B — interruption/retry and installer-state ownership had no
automated coverage.** The issue names both; the lane's only evidence was a
sanitized transcript. One node ID:
`test_interrupted_install_retry_keeps_the_persisted_selection_and_ownership`
pins that a retry re-reads the persisted plan instead of re-probing the
host (a working Docker CLI on the retry host cannot override a persisted
Podman selection), that the recovery file the interrupted run left
half-written is completed for that selection, and that every artifact the
installer writes belongs to the invoking account. It fails if the
persisted-plan branch of `selected_container_runtime` is removed — the
regression the pre-#1820 installer had — which was mutation-checked in
this round.

The delta is confined to the root `tests/` suite: **+3** node IDs. No
package suite moved.
