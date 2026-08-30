---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# claude-issue-668-conductor-tracing-dbb7

Seven added, none removed, none rewritten, all in
`tests/test_telemetry_reports_its_own_absence.py`.

Two are the pair the change exists for: no endpoint stays **silent** (the
ordinary state — a line there would fire on every deployment that never wanted
traces), and a configured endpoint with the packages missing **says so**,
naming both the extra to install and the build argument that gets it into the
image. Asserting the silence matters as much as asserting the message: a fix
that logged unconditionally would satisfy the second and make the first a
permanent false alarm.

The third pins that the report is made once per process. `_init_tracer` runs on
every traced call, so a line per LLM request would bury the one time it
mattered under its own repetition.

The fourth is the constraint the other three must not break: reporting the
absence does not change what the caller gets. A missing exporter is not a
reason to fail an LLM call, and `trace_llm` still yields its context and runs
the body.

Replacing the `logger.error` with `pass` fails exactly the second and third and
leaves the other two passing, which is the check that the report is doing the
work rather than sitting beside it.

Two more came from the diff-coverage gate, and the reason they were missing is
worth writing down: **CI does not install the observability extra** — which is
the whole point of it being an extra — so every test above takes the
ImportError branch and the code *after* those imports is unreachable in that
environment. Nothing was wrong with the tests; the packages simply are not
there.

So the last two install a minimal stub of the five names `_init_tracer`
imports. One proves the path that is the reason for all of this: with the
packages present, a tracer is built, and quietly. The other proves a setup
failure — a bad endpoint, a refused exporter — is reported as its own thing and
*not* as a missing package, because telling an operator to install something
they already have sends them after the wrong problem.

The seventh closes the last branch arc: a *repeated* setup failure is reported
once too. Same restraint as the missing-package report and for the same reason
— `_init_tracer` runs on every traced call, so a provider that keeps refusing
would otherwise write a line per LLM request.
