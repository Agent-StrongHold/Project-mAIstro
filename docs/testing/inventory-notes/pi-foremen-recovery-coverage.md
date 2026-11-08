---
inventory-delta:
  tests/: +92
---

# Coverage repair for the portable Pi foremen/recovery port

Adds 92 root-suite cases under `tests/pi_recovery/` so every new module in
`scripts/pi_recovery/` reaches the diff-coverage floor (90% lines / 80%
branch arcs per file) in the `Coverage gate (publish-set floor + diff
coverage)` producer. No existing case is removed, renamed or moved; the
85 cases recorded by `pi-foremen-recovery` are untouched.

- entrypoint dispatch (`cli.py`): stubbed and real module resolution, the
  progress-unverified error-JSON contract, and `runpy` execution of the
  shipped `__main__` guards.
- session-manager path resolution (`recovery_paths.py`): explicit override,
  flat and bundle npm layouts (the layout that previously made every native
  SDK case skip), and the explicit no-SDK fallback path.
- fresh-configuration guards (`configure.py`): unsafe operator session IDs
  and blanked provider/model are refused before any file is created.
- pane restore (`maistro_pi_pane.py`): intact journal, missing/corrupt
  journal checkpoint restore, identity-mismatch abort, and boot-channel
  signalling on success and failure.
- start modes (`maistro_pi_start.py`): `--check` plan, `--boot` event wait,
  `--ensure` no-attach, attach/switch-client selection, and the
  original-owner duplicate guard.
- resume modes (`maistro_pi_resume.py`): `--check`/`--dry-run` plans,
  `--checkpoint`, `--register-current` (with hermetic environment),
  `--recover-backup` restore, ownership-refusal paths, snapshot integrity,
  journal edge cases, `/proc` identity parse failures, ancestor walk and
  task-projection edge cases.
- foremen reconciliation (`foremen.py`): manifest/role validation, tmux
  inventory parsing, observation fail-closed branches, launch ownership and
  credential gates, `ensure`/`cycle` reconciliation history, escalation
  delivery contracts and progress-attention matrix.

All cases are offline: no agent starts, no provider/GitHub call, no live
tmux server or service is touched beyond the existing opt-in native cases
(which still skip cleanly without their prerequisites).
