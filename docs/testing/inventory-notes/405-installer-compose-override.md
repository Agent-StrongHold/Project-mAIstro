---
inventory-delta:
  tests/: +18
---
# 405-installer-compose-override

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Eighteen root-suite node IDs arrive with #405, all in the new
`tests/test_install_compose_override.py`, which pins the reconciliation of
`docker-compose.override.yml` with the installer's Compose invocation. The
regression being pinned: `install.sh` always invokes compose with explicit
`-f` files, which disables Compose's own automatic override loading, so an
override an operator copied into the checkout was silently ignored on
installer runs while three doc sites (the compose file's own docker-socket
comment included) claimed it was picked up automatically.

The tests lift the real installer functions verbatim (the
`tests/test_install_docker_sock.py` pattern) and drive them against a stub
`docker` that records argv: override included explicitly last in both
delivery modes, absent-override invocation unchanged, wizard plan override
ordered before the operator override, group/world-writable and foreign-owned
overrides refused with remediation, dangling-symlink overrides refused rather
than skipped, `MAISTRO_COMPOSE_PROFILES` (comma or space separated, empty
entries dropped) mapped to `--profile` flags, the pre-startup plan print with
its real `config` validation pass, render failure failing loudly with the
exact command, and the rendered config printed only on
`MAISTRO_PRINT_COMPOSE_CONFIG=1` (it interpolates credentials from `.env`),
and — pinned from a bug the end-to-end smoke run caught after the harness
tests had passed — `ensure_python`'s probe announcement staying out of the
`$(override_file_state …)` capture, so a refusal quotes the real mode rather
than "uid Python found: 3.14.4".
One node renders the real repo compose file through the real Docker Compose
frontend with the documented docker-socket override body and is skipped where
no compose front-end exists; one node (foreign-owner refusal through the real
stat path) is skipped where `chown` to another uid needs privileges — the
foreign-owner branch is still asserted at the decision level in
`test_the_safety_decision_is_exact_over_mode_and_owner`, which needs no
privileges at all.
