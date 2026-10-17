"""M8-D1 planning-strategy benchmark lab (#925).

Test-tree machinery comparing ReAct, explicit plan-and-execute, and the
canonical Graph role pipeline on the same deterministic Goal corpus. It adds
no execution authority: the arms run the shipped ``ReactStrategy``,
``PlanExecuteStrategy`` and ``maistro.graph.GraphRun``/``NodeRun`` exactly as
production drives them, over one shared competent-model policy and one shared
tool world.
"""
