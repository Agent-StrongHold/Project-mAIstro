# #1084 repair checkpoint (job dea951bf)

## Frozen scope
- Only issue #1084, branch `auto-1084`, assigned worktree `/home/dev/Git/wt/auto-1084`.
- Starting HEAD `565dd3d8939c7ab842ff67f8235f9ed8906f2291`; supplied develop `2014ab888c0bff4541a10cc2a808e021e95cb404` resolves and equals local origin/develop at inspection.
- Snapshot sources: supplied dispatch-context.json and check-0.log through check-7.log; no GitHub enumeration/mutation.
- Repair targets: reproduce Quality/Pyright and exact-debt-ledger vulture; resolve develop-sync if present; correct contradictory lane notes based on evidence. Validate existing #1084 egress tests and gates; change production/tests only for reproduced failures. Relevant files frozen to existing #1084 production/tests in `git diff --name-only <supplied-base>..HEAD`, quality/vulture-baseline.json (explicit exception), and these lane notes. Develop merge may introduce upstream files only.
- Initial status clean; no uncommitted salvage required, no merge conflict present.

## Ambiguities and assumptions
- Prompt has generic verifier and writer instructions; assigned lane is repair/writer, so local edits and commit are required.
- Prior closure-keyword finding concerns inherited commit messages. After reproducing the exact nine messages, treat the assigned repair of that supplied blocker as authorizing a bounded local message-only rebuild. Preserve the entire pre-repair graph under a local backup ref, preserve trees/metadata and develop-side ancestry, and atomically update the lane ref only with a clean worktree and identical final tree. No integration, push, branch deletion, or work discard.
- Fetch/merge instruction is conditional on preserved sync conflict. Initial tree is clean, but origin/develop is newer than lane head; inspect ancestry then synchronize the resolved supplied develop ref without re-enumerating GitHub.

## Progress
- Read repository AGENTS.md and supplied dispatch issue body; all ten acceptance criteria remain to be independently checked.
- Existing lane notes contradict themselves on inherited auto-close commit text; prior assertions are not verification evidence.
- Read driver check-0..7 logs: dependency sync, ruff, focused tests (290 + 153), three suite inventories all passed at the starting head. Read previous result artifact; the only previous verifier block was commit-message auto-close text.
- Read accepted ADR-081226-6b46 (Binding/Provider/Invocation), ADR-081426-1f7c (Attempt execution mechanics) and ADR-083026-1cb1 (correlation descriptive, not authorization), plus SPEC-285 observer seam. No alternate runtime/authorization path is permitted.
- Synchronized the exact supplied develop ref via true merge `b1f6709ed5f4`; no conflicts occurred. No remote re-enumeration was needed. Upstream-only quality ledger changes were inherited, not hand-edited.
- CI-exact Pyright replay after `uv sync --locked --all-extras`, editable maistro-evolve, pyright 1.1.414: 827 files, 11 errors/54 warnings, baseline 21, checker exit 0. Diagnostics: `/tmp/1084-dea951bf-pyright.json`. The named failure does not reproduce; no guessed production/type fixes.
- Exact vulture command after merge: 1297 findings == 1297 reviewed identities, base 2014ab888c0b, exit 0. No ledger edits warranted.
- Commit-message scan against the frozen develop base reproduces nine branch-unique keyword-bearing commits (including 61f22af235f1, e9aad735626d, c44240217fe1); the old blanket claim is false. History remains unchanged pending safe bounded decision.
- Production review considered whether GovernedModelChatClient._call could overwrite an operator-disabled Binding. Store inspection resolves this: all Binding stores reject changed definitions and retain revocation tombstones. No reproduced overwrite; no speculative production repair. The current route tests compose real Container services but not real embedded startup, and only the adapter test checks Invocation rows; this is not full same-request acceptance proof.
- Message repair snapshot is exactly the nine reproduced branch-only commits from the frozen supplied develop range: 61f22af235f1, e9aad735626d, 4fd6dafb8a9a, c44240217fe1, 58631e60a677, 0ab0bb698d63, 6124afb907d6, 7c5c6c9a3c31, 43731c7984d0. Replace closure verb with `Refs`, retaining issue references and all other text. Descendant parent hashes necessarily change; no file content or develop ancestor is rewritten.
- First rebuild safely stopped before updating HEAD because a changed commit carried a signature. Backup `refs/heads/auto-1084-before-message-repair-dea951bf` preserves the exact original tip `9a1a92ee8` and its signatures. Rebuilt commits cannot retain valid signatures over different parents/messages: detach signature headers only on rebuilt objects, preserve originals in the backup, and record affected identities. Author/committer timestamps and trees remain unchanged. No worktree edits were discarded.
