#!/usr/bin/env bash
# CI provisioning only, NOT a sandbox for candidate code. Rootless Docker cannot
# manage AppArmor profiles on the hosted runner. Hide securityfs discovery in a
# PRIVATE daemon mount namespace; never unmount securityfs on the host or pass
# apparmor=unconfined to the production sandbox. This lane proves the ADR-093
# Tier-3 contract without AppArmor, not AppArmor or hostile-kernel containment.
set -euo pipefail

if [ "$(id -u)" -eq 0 ] || [ "$#" -eq 0 ]; then
  echo "usage: run as the non-root lane user: $0 command [args...]" >&2
  exit 2
fi
: "${XDG_RUNTIME_DIR:?the rootless lane requires XDG_RUNTIME_DIR}"

# Mount setup alone needs host privilege. Drop back to the invoking uid/gid
# BEFORE rootlesskit/dockerd starts. Do not set no-new-privileges here: newuidmap
# needs its setuid helper to establish subordinate IDs. Candidate processes get
# no-new-privileges from ContainerBuilderSandbox, unchanged.
exec sudo -n unshare --mount --propagation private bash -euc '
  mount -t tmpfs -o ro,nosuid,nodev,noexec,size=4k maistro-ci-securityfs /sys/kernel/security
  exec setpriv --reuid="$1" --regid="$2" --init-groups \
    env HOME="$3" XDG_RUNTIME_DIR="$4" PATH="$5" "${@:6}"
' bash "$(id -u)" "$(id -g)" "$HOME" "$XDG_RUNTIME_DIR" "$PATH" "$@"
