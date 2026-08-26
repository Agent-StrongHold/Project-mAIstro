---
inventory-delta:
  tests/: +14
  packages/hive-conductor/backend/tests: +14
---
# claude-issue-413-close-gate-gaps

Twenty-eight new node IDs across four existing files. Nothing removed or
reparametrised. Eleven of the conductor IDs are two parametrised tests over the
design routes, so adding a route moves that count without any file changing.

Measured against the pre-fix tree: **18 of the 28 fail**, spread across all five
gaps. The ten that pass are the cases that were already correct and are pinned
so they stay that way — `GET /design/systems` already answered 503, the tier
split already excluded bundled slugs, a module-level `try` binding already
counted.

## Why these are follow-ups rather than part of #293

Codex reviewed PR #298 after it merged. Three of its five findings are the
defect #293 was about, one step short — which is the useful thing to record:
fixing a swallowed failure in one place does not fix the swallow.

## `tests/` — the two gates (+14)

`TestOnlyModuleScopeCounts` is the sharpest. `_names_in` walked the whole AST,
so a name bound inside a function counted as a module attribute. Verified
directly against the old code: for `def build(): helper = 1`, it returned
`['build', 'helper']` — so `from thing.local import helper` resolved against
something no importer can reach, which is the exact missing-attribute case the
gate exists to catch, passing it.

The cases that must keep working are the other half, and they are why this is
not simply "don't recurse": `try: import x / except ImportError: x = None` and
`if TYPE_CHECKING:` are how these packages do conditional exports, and both are
still module scope. A class body is not, and neither is a function body.

`TestTheScanCoversWhatItClaims` records an overclaim rather than a bug. The
docstring promised "every first-party Python file, tests included" and gave the
reason — a missing *name* can sit inside a `pytest.raises` and never say so —
while the glob covered `packages/` only, leaving the root `tests/`, `scripts/`,
`alembic/` and `formal/` outside. Measured when they were added: 207 further
files, **zero** new findings. The claim was the only thing that was wrong.
`test_widening_did_not_cost_coverage_elsewhere` holds the file count above a
floor so a tree cannot silently drop back out.

`TestTheOptionalFileIsDeclared` covers the wheel gap, and it is the one with
the sharpest consequence. `design-tokens.json` is the single file
`_read_system_files()` treats as optional, and the one carrying every colour
and spacing token. Dropped in packaging: the wheel imports, `load_bundled`
succeeds, startup reports ready, and every bundled system loads with zero
tokens — the empty shell #293 removed, reached from the other direction. The
file whose absence is silent is the one that most needs declaring.
`test_all_four_essential_files_are_declared_per_system` counts against
`ESSENTIAL_FILES` rather than the literal 4, so a fifth file added upstream
shows up as a gap instead of going unchecked.

## `packages/hive-conductor/backend/tests` — the product (+14)

`TestEveryEngineRouteReportsTheCause` is parametrised over every design route
because the defect was distributional: #293 gave startup an answerable status
and exactly one route asked. The rest caught the generic
`RuntimeError("DesignEngine not initialized …")` in a blanket handler and
returned 500, discarding both the recorded cause and the service-unavailable
semantics. A broken install answered "internal server error" on five routes out
of six.

`test_the_recorded_cause_reaches_the_caller` is the assertion that matters more
than the status code. A 503 saying only "unavailable" is the log line again;
the cause is what #293 added and what these routes were dropping.
`test_a_ready_service_is_not_affected` is the guard against overcorrection —
the readiness check must not have made working routes fail.

`TestTheCatalogClaimIsVerified` closes the last gap. `_probe_catalog` read
`catalog.json` and reported its 144 slugs as available; `import_from_catalog`
reads `systems/catalog/<slug>/`, not the index. A build carrying the index
without the payloads advertised 144 importable systems and failed every one on
click. The index is a claim; the files are the fact.

The partial case is deliberately *degraded* rather than unavailable — what is
installed can still be imported, and `"1 of 2 indexed system(s) have no files
installed"` is something a reader can act on, where a round number is not.
`test_the_bundled_tier_is_still_excluded` pins that #293's tier split survives
the payload check: `default` lives under `systems/bundled/`, so a naive probe
against `systems/catalog/` would drop it for entirely the wrong reason.
