# PR #1274 round-2 formal conformance repair

The memory-scope property test kept its existing node count, but its generated
GLOBAL memories now carry the generated organization filter whenever they are
organization-bound. The production visibility rule intentionally refuses an
organization-bound GLOBAL memory without tenant context; the old generator
created one and then queried it without that context, making the property
contradict its own isolation contract. No test surface was added or removed, so
no count moved.

The same repair exposes `RetentionScope` as a module-level alias that the
cross-package import gate can resolve. The Python 3.12 `type` statement created
a valid typing alias but was invisible to the repository's AST inventory.
