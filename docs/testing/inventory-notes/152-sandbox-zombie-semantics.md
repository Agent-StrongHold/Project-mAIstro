# 152 — a zombie reads as stopped

One maistro-rsi node ID pins the property the sandbox group-kill test depends
on (#152): a zombie reads as stopped. The old check asked `os.kill(pid, 0)`,
which a killed-but-unreaped process answers for as long as nothing reaps it, so
the suite reported a containment failure about a process the kernel had already
killed. Forking a child that exits without being reaped makes that state
unambiguous, so the helper's semantics are held rather than assumed.
