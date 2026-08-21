# .cursor/context/

Files here are **optional shared context** for agents and subagents. Nothing in this folder is auto-injected into every chat.

**When to add a file**

- Architecture summaries that are too long for `AGENTS.md` but needed repeatedly.
- Onboarding notes for a specific subsystem (e.g. memory tiers, builder pipeline).
- Glossary of internal names (orchestrator, conduit, warden, sentinel, etc.).

**How to use**

- Reference paths explicitly in prompts (e.g. “read `.cursor/context/foo.md`”).
- For **subagents**, paste goal, constraints, and file paths into the Task prompt — subagents do not see prior chat history.
