# Formal security conformance

The formal gate measures behavior against the independently governed fixture
`formal/fixtures/security_oracle.json`. It does not extract constants from
candidate source. The fixture is a reviewable security model, not a cache of
implementation text.

| Claim | Oracle cases | Measured property | Formal test |
|---|---|---|---|
| ADR-072 destructive input is denied | `dangerous_commands` | Every adversarial command is denied and each case has its governed effective-match cardinality | `formal/models/test_dangerous_tools.py::test_dangerous_commands_match_oracle` |
| ADR-072 benign context cannot launder destructive input | `dangerous_commands` | Every governed command stays denied after benign prefix/suffix composition (`echo setup; …`, `cd /tmp && …`, `… # comment`), so a shadowing short-circuit cannot silence the deny rules | `formal/models/test_dangerous_tools.py::test_composition_cannot_launder_dangerous_command` |
| ADR-073 fast-tier command detection is live | `dangerous_commands`, `safe_commands` | Hypothesis samples preserve deny/allow behavior; every single-rule deletion mutation changes at least one measured case | `formal/models/test_dangerous_tools.py::test_command_rule_deletion_cannot_pass` |
| SPEC-190 the executor, not just the predicate, enforces denial | `dangerous_commands`, `safe_commands` | `MicroVMSandbox.exec` (the production `SandboxExec` seam) refuses every governed dangerous command before its launcher runs, and still runs governed benign commands — a detector made unreachable from production is a measured failure | `formal/models/test_dangerous_tools.py::test_enforcement_path_refuses_oracle_commands`, `test_enforcement_path_runs_oracle_safe_commands` |
| ADR-073 high-risk tools require detection | `dangerous_tools`, `safe_tools` | Dangerous names are recognized case-insensitively and benign names are not | `formal/models/test_dangerous_tools.py::test_dangerous_tool_oracle`, `test_safe_tool_oracle` |
| SPEC-190 host boundary is denied | `blocked_paths`, `allowed_paths` | Boundary roots and descendants are denied while ordinary workspace paths remain allowed | `formal/models/test_dangerous_tools.py::test_blocked_path_oracle`, `test_allowed_path_oracle` |

The fixture has 41 dangerous-command cases covering the 22 semantic rules
currently required by the security claim. Beyond one exact witness per rule,
each rule carries narrowing witnesses (flag variants, alternate targets,
alternate syntax) so that tightening a rule to only its original witness
string — e.g. `sudo\s+` → `sudo\s+apt` — changes a measured case. The extra
`rm -rf ~` case is a boundary witness for the destructive-command rule. The
deletion property is a runtime mutation test: it removes each detector in turn
and requires the independently authored expected behavior to change. This is
the CI demonstration that the 21-of-22 deletion mutation cannot pass by
preserving a source-token count.

`formal/models/test_external_content.py` independently exercises adversarial
prompt-injection payloads and normalization behavior. Its inputs are behavior
fixtures in the test model, not extracted constants.
