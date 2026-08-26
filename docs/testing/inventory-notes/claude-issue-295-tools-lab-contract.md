---
inventory-delta:
  tests/: +54
---
# claude-issue-295-tools-lab-contract

Fifty-four new node IDs in one file, all testing the new gate in `scripts/`.
Nothing removed or reparametrised — the Tools Lab page had no tests, which is
part of why it shipped calling three endpoints nobody wrote.

## Why the gate needed its own tests at all

`check-frontend-api-routes.py` currently finds nothing: the facade it was
written for is removed in the same change. A guard with nothing left to catch
and no tests is a guard nobody knows is broken, so these are the only thing
keeping its rules honest.

Verified by hand against the pre-fix tree before writing them: restoring
`ToolsLab.tsx` makes the gate report all three call sites, at the right lines.

## The two failure directions

`TestTheDefectItWasWrittenFor` is the direction that matters if the matcher
degrades. `test_a_path_whose_first_segment_is_unregistered_cannot_be_saved_by_a_tail`
records why the weaker prefix claim is still sufficient here: `/v1/tools-lab`
was the prefix of no registered route, so no amount of unresolvable tail could
have made those calls land.

`TestWhatMustNotBeFlagged` is the other direction, and it is the one that
decides whether this gate survives. This frontend uses three idioms a naive
reader gets wrong, and all three were false positives in the first version:

- `` `/v1/audit${qs ? `?${qs}` : ""}` `` — a *query string*, not a path
  segment. The nested backtick also means it cannot be parsed as an id, so the
  path truncates there and the claim downgrades to a prefix rather than
  inventing a segment that is never requested.
- `` `/v1/dags/${id}/nodes` `` — a well-formed interpolation *is* one segment,
  so the path stays a complete claim and the segment count still has to agree.
  `test_a_well_formed_interpolation_is_a_segment_not_a_downgrade` pins that the
  two cases stay distinguishable.
- `/v1/agents/researcher` against `/v1/agents/{agent_id}` — a hardcoded known
  id. The route serves it; flagging it would hit every page.

`test_segment_counts_must_agree_when_the_path_is_complete` is the guard on the
guard: without it every call matches its own prefix and the gate passes
everything while appearing to check.

## `TestBaseConstants` — the resolution that removed two false positives

`const API = "/v1/evolution"` composed as `${API}/status`. Left unresolved this
is wrong twice: the base reports as unregistered (nothing is mounted at
`/v1/evolution` itself) and the eight real calls built from it stay invisible.
Resolving bindings fixes both, which is why it is worth the extra reader
rather than simply accepting prefix matches everywhere.

## `TestItRefusesToGuess` — the half that keeps it from being harmful

Four routers are mounted inside a `try`. Checked against a table missing one,
every call into it reports as unregistered and the real cause is an import
error a layer down — so the gate declines to answer instead of answering
wrongly. That refusal is not hypothetical: run as a bare CI step without the
workspace on `sys.path`, the first version did exactly this for
`routes.design`, which is how the missing `sys.path` setup was found.

An empty route table, an empty file list and an empty call list are each
asserted to fail rather than pass, for the same reason as every other gate
here: reporting green because it could not tell converts "we do not know" into
"we checked".

## `TestTheReport` and `TestTheImportPaths`

What the gate prints is part of what it does — someone reads it while deciding
whether to trust a merge. `test_it_explains_why_a_404_is_not_self_announcing`
covers the half that is easy to leave out: without the reason, the obvious
reading of "this path reaches no route" is "the backend is down".

`test_the_same_call_is_listed_once` guards a detail the first version got
wrong. A finding is generated per non-matching route, so a single bad call
printed once per registered route — 195 identical lines reading as 195
defects.

`TestTheImportPaths` pins the ordering that made this work as a bare step.
BACKEND is last in the list and therefore first on the path, because the
monorepo root has a `services/` package that shadows the app's own when it wins
the race — the same hazard `backend/tests/conftest.py` already guards against.

## `TestTheRepository`

Against the real app and the real frontend — 161 call sites across 56 files
resolving to 195 registered routes. `test_it_is_actually_measuring_something`
holds those counts above a floor, because a scan that silently shrank would
report a clean tree by checking almost nothing.


## Review round: four more classes (+23)

Codex reviewed the first version and found four defects in it. All four were
real, all four are covered here, and one of them found a second broken control
in the product.

`TestTheVerbIsCheckedToo` is the one that earned its keep immediately. A path
match alone accepts a GET against a POST-only route -- Starlette answers 405
and the control is as broken as if nothing were registered. Comparing verbs
exposed `apiPost("/v1/agents/scan")`: a live Agent Builder button posting to a
path that does not exist, which the path-only matcher had accepted against
`GET /v1/agents/{agent_id}` because a route parameter swallows any single
segment. Filed as #418 and waived on the line with that number, so this PR
stays scoped and the gate still lands green.

`TestAnInterpolationGluedToASegmentIsASuffix` covers the subtlest one, and it
was a false *negative* -- the direction that matters most for a gate.
`/v1/optimizer/proposals${query}` became `/v1/optimizer/proposals/*`, which
matched `/v1/optimizer/{dag_id}/proposals` and `/v1/optimizer/{dag_id}/run`,
neither of them the route being called, and did **not** match the real
`/v1/optimizer/proposals`. Deleting that route would have left the gate green.
Adjacency is the rule now: an interpolation between slashes is an id, one glued
to the segment before it is a suffix.

Fixing that surfaced a second ordering bug in my own parser, caught by an
existing test rather than by review: `/v1/audit${qs ? `?${qs}` contains a
*well-formed* interpolation after an unparseable one, so searching for the
first parseable match skipped past the real boundary and produced a segment
reading ``audit${qs ? `?``. The loop now always works from the first `${`.

`TestABaseHandedOverWhole` closes a hole the base-binding resolution opened:
binding lines are skipped as "not a call" and only template uses were resolved,
so `const API = "/v1/missing"; fetch(API)` produced no Call at all.

`TestTheFeatureInventory` is one line, and the least interesting until you
notice it is the same defect as the page: `README.md` listed Tools Lab as a
shipped surface after its route and nav entry were gone.
