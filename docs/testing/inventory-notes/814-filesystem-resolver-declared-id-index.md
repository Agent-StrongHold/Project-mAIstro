---
inventory-delta:
  packages/maistro-registry/tests: +11
---
# 814 filesystem resolver resolves declared ids (+11)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`FilesystemResolver` resolved `<repo>#<id>` references by filename prefix
(`f.name.startswith(f"{item_id}-")`) over a non-recursive `iterdir()` of
`docs/adr` and `docs/specs` — a second identity authority beside the
front-matter `id` the registry itself validates (#814). A file whose name
implies one id while its front matter declares another made the undeclared
id resolve, and nested spec files were invisible to it. Resolution now
consumes the registry walk's validated front-matter id index
(`maistro_registry.walk.declared_ids`), and `lint` passes the index it
already built instead of letting the resolver rebuild it.

`test_filesystem_resolver.py` (+11, all tmp-tree, no corpus fixtures):

- matching id resolves; filename/id disagreement resolves only the declared
  id (kills the prefix matcher and `return True` alike);
- missing front matter and schema-invalid ids declare nothing, however
  canonical the filename;
- duplicate declared id still resolves (existence is the resolver's only
  question; ambiguity stays with `find_duplicate_ids`);
- undeclared id does not resolve when other records exist (kills the
  "any record exists → resolve" mutant);
- nested spec paths are indexed (kills the `iterdir()` non-recursion);
- template files are not records (the walk's skips are load-bearing);
- non-engine repos stay optimistic and an empty root fails closed;
- end-to-end `lint`: a relationship pointing at a filename-implied id
  dangles while the declared id resolves — on the pre-fix code this exact
  tree printed DANGLING for the *declared* id and none for the implied one.
