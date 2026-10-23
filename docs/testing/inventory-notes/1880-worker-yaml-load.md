---
inventory-delta:
  packages/maistro-server/tests: +6
---

# 1880 — the server worker loads the operator YAML before Container startup

Issue #1880: `maistro_server.entrypoint.main` runs the schema migrations and
then `os.execvp`s uvicorn, so a YAML singleton loaded in that parent dies with
the exec'd-away interpreter. The worker now calls the existing
`maistro.config.loader.load_yaml_config` itself, as the first YAML consumer in
`main._runtime_lifespan` (before `_validate_startup`'s `_router_api_key` and
before `_agent_config`'s `_security_config` / `_model_bindings` reach
`create_container`), and a malformed or type-invalid file stops startup with a
sanitized `operator_yaml_config_invalid` event instead of booting silently on
the fail-closed defaults.

Six new node IDs in `packages/maistro-server/tests/test_model_config_process_startup.py`:

- valid explicit file — the real lifespan (entered the way uvicorn enters it,
  with only the composition factory stubbed) yields a Container config that
  carries the file's Binding declarations, with a structural
  `yaml_loaded -> container_composed` ordering record; the YAML is the only
  source of `router_api_key`, so the test fails if the worker hook is absent;
- explicitly named missing file — startup still reaches composition on the
  empty fail-closed defaults (the `TestLoadRawYaml` missing-file contract is
  preserved, not made fatal);
- malformed YAML and typed-invalid YAML — each stops the worker before the
  composition factory is entered, raises a sanitized error with the chained
  parser exception suppressed (`from None`), leaves the singleton unassigned,
  and a synthetic secret planted in the invalid input appears in neither the
  error chain nor the captured process stderr while the sanitized event does;
- two fresh-subprocess cases — a genuine new Python process running the real
  worker hook reads the file's current declarations (the file is rewritten
  between two worker runs), and a real worker given malformed YAML exits
  non-zero with the secret absent from its actual stderr.

None of the new tests preloads the YAML singleton; the suite conftest now also
resets it around every test, because the lifespan legitimately sets it and a
leaked singleton would shadow the env fallbacks `_validate_startup`
(`TestRouterApiKeyValidation`) and the loader are specified against — two
startup tests otherwise fail when the whole server suite runs in one session.
