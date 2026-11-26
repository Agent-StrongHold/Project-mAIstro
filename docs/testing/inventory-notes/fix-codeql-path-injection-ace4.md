---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +1
  packages/maistro-rsi/tests: +5
---
# fix-codeql-path-injection-ace4

Clear remaining open CodeQL ``py/path-injection`` alerts by switching each
site to the sanitizer CodeQL models (``os.path.realpath`` +
``startswith(root + os.sep)``), instead of ``Path.resolve()`` /
``is_relative_to`` which the query does not treat as a barrier.

- ``test_rsi_execution_containment.py`` (+1): ``..`` traversal out of an
  authorized RSI root is refused after realpath.
- ``test_workspace.py`` (+1): realpath symlink escape after a lexical pass
  is still refused; existing symlink case now mkdir's the allowlisted root.
- ``test_ui_auto_climb_defaults.py`` (+1 hive): ``main()`` parses argv and
  runs ``auto_climb`` (covers the climber CLI entry for diff-coverage).
- ``test_rsi_container_dispatch.py`` (+2 hive): ``work_root()`` publishes
  ``RSI_WORK_ROOT`` via ``setdefault`` and does not clobber an operator env.
- ``test_promotion_export_paths.py`` (+5): stem allowlist gains space /
  semicolon / overlong cases; leaf-symlink race patches ``builtins.open``;
  export directory must sit under platform temp / ``RSI_WORK_ROOT`` /
  ``RSI_EXPORT_ROOTS`` so ``makedirs``/``glob`` are startswith-dominated;
  env pathsep roots are realpath'd into the allowlist.
- ``test_service_paths.py`` (+5, not inventory-gated — no CI recipe collects
  ``packages/maistro-canvas/frontend/server/lulu/tests``): library
  ``preflight_interior`` / ``preflight_cover`` refuse outside/symlink paths
  with ``PATH_OUTSIDE_ROOT``, and a path inside the root still reaches PDF
  parsing.
