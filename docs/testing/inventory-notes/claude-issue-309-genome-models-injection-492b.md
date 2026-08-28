---
inventory-delta:
  packages/maistro-rsi/tests: +88
---
# claude-issue-309-genome-models-injection-492b

All eighty-eight are new, in three modules, and nothing was removed or renamed.

`test_model_identifiers.py` (+49) is the grammar: the aliases real deployments
use, then the acceptance criteria's list one class each — the demonstrated
payload, shell metacharacters, newlines, option injection, eight Unicode
separators, the length and cardinality limits, and the shell-facing CLI's
stdout/stderr split. Five more cover `--single` and the claim that the module
imports only the standard library -- running it through `-m` would initialise
the package, whose `__init__` pulls in `coordinator` and third-party
dependencies, so a valid roster would exit 64 on exactly the Docker-only host
the wrapper is written for.

`test_run_rsi_isolated_wrapper.py` (+24) drives the real `tools/run_rsi_isolated.sh`
with a fake `docker` on PATH that records its argv and exits. These are about
what the wrapper was *about to run*: the payload holds no roster, every value
arrives as an `-e` flag, and a refused roster starts no container at all. The
fixture writes a fake gateway `.env` on purpose — without one the wrapper exits
early and every "no container started" assertion would pass vacuously.

`test_run_model_arguments.py` (+15) covers the Python entry point, which
validates the same four arguments and, unlike the launcher, holds the free-router
expansion built out of a network response.

Three more cover the single-valued `MAISTRO_RSI_LOCAL_FALLBACK_MODEL`, which
the in-container CLI refused only after the gateway credentials were mounted.

Several of the wrapper ones are slower than the rest (they run bash), and all three
modules skip cleanly where `bash` is absent.
