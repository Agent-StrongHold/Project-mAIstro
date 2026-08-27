---
inventory-delta:
  packages/maistro-rsi/tests: +80
---
# claude-issue-309-genome-models-injection-492b

All eighty are new, in three modules, and nothing was removed or renamed.

`test_model_identifiers.py` (+44) is the grammar: the aliases real deployments
use, then the acceptance criteria's list one class each — the demonstrated
payload, shell metacharacters, newlines, option injection, eight Unicode
separators, the length and cardinality limits, and the shell-facing CLI's
stdout/stderr split.

`test_run_rsi_isolated_wrapper.py` (+21) drives the real `tools/run_rsi_isolated.sh`
with a fake `docker` on PATH that records its argv and exits. These are about
what the wrapper was *about to run*: the payload holds no roster, every value
arrives as an `-e` flag, and a refused roster starts no container at all. The
fixture writes a fake gateway `.env` on purpose — without one the wrapper exits
early and every "no container started" assertion would pass vacuously.

`test_run_model_arguments.py` (+15) covers the Python entry point, which
validates the same four arguments and, unlike the launcher, holds the free-router
expansion built out of a network response.

Two of the twenty-one are slower than the rest (they run bash), and all three
modules skip cleanly where `bash` is absent.
