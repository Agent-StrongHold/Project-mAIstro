---
inventory-delta:
  packages/maistro-bootstrap/tests:  +5
---
# claude-repair-wizard-preflight-coverage-c7d5

Five tests appended to `packages/maistro-bootstrap/tests/test_sandbox_preflight.py`,
covering the installer's sandbox preflight banner. Nothing removed or renamed.

They exist because #600 merged with these lines untested — I read the
`gates-ran` summary rather than the coverage job it summarised, and it reported
success on a head where that job had already failed. The banner is the only
place #81's claim reaches an operator, so it was the part of that change least
able to afford being unverified.

Three pin what `preflight_lines()` returns: that the sandbox line sits beside
the hypervisor inventory (the two used to be conflated), that a host which
cannot isolate is the one line rendered in warning colour, and that a host
which can is not shouted about. Two more pin the seam to the operator, which
is what makes the first three worth anything: that `print_preflight()` prints
every line it is given, and that the banner is emitted before the wizard asks
its first question — proven by stopping at that first prompt rather than by
finding the text somewhere in the transcript.
