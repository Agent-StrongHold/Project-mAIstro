---
inventory-delta:
  tests/: +22
---

# #807 the installer invokes only defined or deliberately external functions

`tests/test_check_install_functions.py` (new file, 22 node IDs) pins
`scripts/check-install-functions.py` (new gate, AC-4): the static check that
asserts every word install.sh/get.sh can place in command position is a
function defined in the same file, a bash reserved word or builtin, or an
entry in `EXTERNAL_COMMANDS` with a recorded justification. shellcheck cannot
provide this — it does not report calls to undefined functions (SC analysis
assumes sourced content it cannot see), which is how `upsert_env` shipped
green on every gate.

`TestTheRealInstallers` keeps both supported entry points clean and replays
the original defect: planting `upsert_env` back at the real call site must be
flagged by name. `TestExtractionShapes` pins the command-position extractor on
synthetic sources — substitution contents (including inside double quotes)
are commands, while quoted prose, `case` patterns, array literals, heredoc
bodies, backslash continuations, arithmetic and parameter-expansion names are
data; a variable in command position (`"${UV_CMD[@]}" tool install`) yields no
candidate because its followers are arguments. `TestTheGateContract` requires
every allowlist entry to carry a justification, and exercises `main`'s
pass/fail/missing-target exits.
