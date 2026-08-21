"""Builder/Engineering DAGs — 5 multi-node pipelines for engineering tasks."""

DAGS = [
    {
        "id": "eng_code_review",
        "name": "Code Review Pipeline",
        "department": "engineering",
        "description": "Plan → code → review → test pipeline",
        "nodes": [
            {
                "id": "plan",
                "prompt": "Create an implementation plan for: {input}. Include approach, files to modify, edge cases, and testing strategy.",
                "model": "o3-pro",
                "role": "architect",
            },
            {
                "id": "implement",
                "prompt": "Write the implementation based on this plan. Include type annotations, error handling, and docstrings. Plan: {plan}",
                "model": "o3-pro",
                "role": "developer",
            },
            {
                "id": "review",
                "prompt": "Review this code for: bugs, security issues, performance problems, style violations, and missing edge cases. Code: {implement}",
                "model": "o3-pro",
                "role": "reviewer",
            },
            {
                "id": "test",
                "prompt": "Write comprehensive tests: unit tests, edge cases, error cases, and integration tests. Code: {implement}\nReview feedback: {review}",
                "model": "claude-opus-4-6",
                "role": "tester",
            },
        ],
        "edges": [
            {"from_node": "plan", "to_node": "implement"},
            {"from_node": "implement", "to_node": "review"},
            {"from_node": "implement", "to_node": "test"},
            {"from_node": "review", "to_node": "test"},
        ],
        "evals": ["TestsPass", "Coverage", "Security", "StyleMatch", "ReviewScore"],
    },
    {
        "id": "eng_bug_fix",
        "name": "Bug Fix Pipeline",
        "department": "engineering",
        "description": "Reproduce → diagnose → fix → verify",
        "nodes": [
            {
                "id": "reproduce",
                "prompt": "Analyze this bug report and create reproduction steps. Identify the expected vs actual behavior. Bug: {input}",
                "model": "claude-opus-4-6",
                "role": "tester",
            },
            {
                "id": "diagnose",
                "prompt": "Diagnose the root cause. Trace the code path, identify the faulty logic, and explain why it fails. Reproduction: {reproduce}",
                "model": "o3-pro",
                "role": "developer",
            },
            {
                "id": "fix",
                "prompt": "Write the minimal fix that addresses the root cause without introducing regressions. Include before/after. Diagnosis: {diagnose}",
                "model": "o3-pro",
                "role": "developer",
            },
            {
                "id": "verify",
                "prompt": "Write a regression test that would have caught this bug. Verify the fix handles edge cases. Fix: {fix}",
                "model": "claude-opus-4-6",
                "role": "tester",
            },
        ],
        "edges": [
            {"from_node": "reproduce", "to_node": "diagnose"},
            {"from_node": "diagnose", "to_node": "fix"},
            {"from_node": "fix", "to_node": "verify"},
        ],
        "evals": ["TestsPass", "Security", "ReviewScore"],
    },
    {
        "id": "eng_adr",
        "name": "Architecture Decision Record Generator",
        "department": "engineering",
        "description": "Generate ADRs from architectural decisions",
        "nodes": [
            {
                "id": "context",
                "prompt": "Describe the architectural context and problem being solved: {input}. Include constraints, requirements, and quality attributes.",
                "model": "claude-opus-4-6",
                "role": "architect",
            },
            {
                "id": "options",
                "prompt": "Enumerate 3-5 architectural options. For each: description, pros, cons, and trade-offs. Context: {context}",
                "model": "o3-pro",
                "role": "architect",
            },
            {
                "id": "decide",
                "prompt": "Recommend one option with clear justification. Address why alternatives were rejected. Options: {options}",
                "model": "o3-pro",
                "role": "architect",
            },
            {
                "id": "adr",
                "prompt": "Format as an ADR: Title, Status, Context, Decision, Consequences, Alternatives Considered. Decision: {decide}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "context", "to_node": "options"},
            {"from_node": "options", "to_node": "decide"},
            {"from_node": "decide", "to_node": "adr"},
        ],
        "evals": ["ReviewScore", "StyleMatch", "Coverage"],
    },
    {
        "id": "eng_api_design",
        "name": "API Design Pipeline",
        "department": "engineering",
        "description": "Spec → implementation → docs",
        "nodes": [
            {
                "id": "spec",
                "prompt": "Design a REST API for: {input}. Include endpoints, methods, request/response schemas, auth, and error codes. Use OpenAPI style.",
                "model": "o3-pro",
                "role": "architect",
            },
            {
                "id": "implement",
                "prompt": "Implement the API endpoints with proper validation, error handling, and middleware. Spec: {spec}",
                "model": "o3-pro",
                "role": "developer",
            },
            {
                "id": "docs",
                "prompt": "Write API documentation: endpoint descriptions, examples, authentication guide, rate limits, and error reference. Implementation: {implement}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "spec", "to_node": "implement"},
            {"from_node": "implement", "to_node": "docs"},
        ],
        "evals": ["Security", "StyleMatch", "Coverage"],
    },
    {
        "id": "eng_migration",
        "name": "Migration Planner",
        "department": "engineering",
        "description": "Plan migration from old system to new system",
        "nodes": [
            {
                "id": "audit",
                "prompt": "Audit the current system: components, dependencies, data stores, integrations, and pain points. System: {input}",
                "model": "o3-pro",
                "role": "architect",
            },
            {
                "id": "design",
                "prompt": "Design the target architecture addressing current pain points. Include data migration strategy. Audit: {audit}",
                "model": "o3-pro",
                "role": "architect",
            },
            {
                "id": "plan",
                "prompt": "Create a phased migration plan: parallel run, feature flags, rollback strategy, and success criteria. Design: {design}",
                "model": "claude-opus-4-6",
                "role": "planner",
            },
            {
                "id": "risks",
                "prompt": "Identify migration risks and create mitigation strategies. Include rollback procedures for each phase. Plan: {plan}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
        ],
        "edges": [
            {"from_node": "audit", "to_node": "design"},
            {"from_node": "design", "to_node": "plan"},
            {"from_node": "plan", "to_node": "risks"},
        ],
        "evals": ["ReviewScore", "Security", "Coverage"],
    },
]
