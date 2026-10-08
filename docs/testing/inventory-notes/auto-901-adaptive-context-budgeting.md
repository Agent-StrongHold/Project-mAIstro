---
inventory-delta:
  packages/maistro-core/tests: +2
---
# #901 Adaptive context budgeting exploration

This implements a simple adaptive context assembly policy that adjusts the
context budget based on query length as a prototype for exploring adaptive
top-k/context budgeting (issue #922). The policy increases the budget for
long queries (indicating complex tasks) and decreases it for short queries.

The tests verify that the adaptive policy correctly modifies the budget.
A second test is a placeholder for future work on verifying that the budget
change affects inclusion of budget-dependent memories.

This is a spike for the epic #901 to explore advanced memory, retrieval,
consolidation, and context intelligence.
