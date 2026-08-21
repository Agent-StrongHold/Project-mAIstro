"""Product Management DAGs — 5 multi-node pipelines for PM tasks."""

DAGS = [
    {
        "id": "pm_prd_generator",
        "name": "PRD Generator",
        "department": "product_management",
        "description": "From vague idea to full product requirements document",
        "nodes": [
            {
                "id": "clarify",
                "prompt": "Take this vague product idea and extract: problem statement, target user, success metrics, and constraints. Idea: {input}",
                "model": "claude-opus-4-6",
                "role": "pm",
            },
            {
                "id": "research",
                "prompt": "Research existing solutions and identify gaps. What's been tried? What failed? What's the opportunity? Context: {clarify}",
                "model": "o3-pro",
                "role": "researcher",
            },
            {
                "id": "requirements",
                "prompt": "Write detailed requirements: user stories (As a... I want... So that...), acceptance criteria, non-functional requirements. Research: {research}",
                "model": "o3-pro",
                "role": "pm",
            },
            {
                "id": "scope",
                "prompt": "Define MVP scope: what's in v1, what's deferred. Include effort estimates and dependencies. Requirements: {requirements}",
                "model": "claude-opus-4-6",
                "role": "pm",
            },
            {
                "id": "prd",
                "prompt": "Assemble into a complete PRD with: overview, goals, user stories, technical requirements, timeline, risks, and success metrics. All content: {scope}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "clarify", "to_node": "research"},
            {"from_node": "research", "to_node": "requirements"},
            {"from_node": "requirements", "to_node": "scope"},
            {"from_node": "scope", "to_node": "prd"},
        ],
        "evals": ["RequirementsCompleteness", "DecompositionQuality", "TimelineRealism"],
    },
    {
        "id": "pm_sprint_planning",
        "name": "Sprint Planning Assistant",
        "department": "product_management",
        "description": "From backlog to sprint scope with capacity planning",
        "nodes": [
            {
                "id": "assess",
                "prompt": "Assess this backlog and team capacity. Identify blockers, dependencies, and velocity. Backlog: {input}",
                "model": "claude-opus-4-6",
                "role": "pm",
            },
            {
                "id": "prioritize",
                "prompt": "Prioritize items using RICE framework (Reach, Impact, Confidence, Effort). Score each item. Assessment: {assess}",
                "model": "o3-pro",
                "role": "pm",
            },
            {
                "id": "scope_sprint",
                "prompt": "Select items for this sprint based on priority, capacity, and dependencies. Explain tradeoffs. Priorities: {prioritize}",
                "model": "claude-opus-4-6",
                "role": "pm",
            },
            {
                "id": "plan",
                "prompt": "Create sprint plan: goals, committed items, stretch items, risks, and daily focus areas. Sprint scope: {scope_sprint}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "assess", "to_node": "prioritize"},
            {"from_node": "prioritize", "to_node": "scope_sprint"},
            {"from_node": "scope_sprint", "to_node": "plan"},
        ],
        "evals": ["PrioritizationLogic", "DecompositionQuality", "TimelineRealism"],
    },
    {
        "id": "pm_stakeholder_update",
        "name": "Stakeholder Update Generator",
        "department": "product_management",
        "description": "Generate tailored stakeholder updates from raw progress data",
        "nodes": [
            {
                "id": "extract",
                "prompt": "Extract key progress metrics, blockers, and decisions needed from this raw data: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "tailor",
                "prompt": "Tailor this update for different audiences: executives (high-level), engineering (technical), and customers (value-focused). Data: {extract}",
                "model": "o3-pro",
                "role": "pm",
            },
            {
                "id": "format_update",
                "prompt": "Format as a professional stakeholder update email with: TL;DR, progress, blockers, asks, and next milestones. Content: {tailor}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "extract", "to_node": "tailor"},
            {"from_node": "tailor", "to_node": "format_update"},
        ],
        "evals": ["StakeholderAlignment", "RequirementsCompleteness"],
    },
    {
        "id": "pm_feature_prioritization",
        "name": "Feature Prioritization Framework",
        "department": "product_management",
        "description": "Score and rank features using multiple frameworks",
        "nodes": [
            {
                "id": "inventory",
                "prompt": "List and categorize all feature requests. Group by theme and user segment. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "pm",
            },
            {
                "id": "score",
                "prompt": "Score each feature on: user value (1-10), business value (1-10), effort (1-10), risk (1-10). Justify each score. Features: {inventory}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "rank",
                "prompt": "Rank features by weighted score. Show the math. Identify quick wins vs strategic bets. Scores: {score}",
                "model": "claude-opus-4-6",
                "role": "pm",
            },
            {
                "id": "roadmap",
                "prompt": "Place ranked features on a quarterly roadmap. Note dependencies and resource constraints. Rankings: {rank}",
                "model": "claude-opus-4-6",
                "role": "planner",
            },
        ],
        "edges": [
            {"from_node": "inventory", "to_node": "score"},
            {"from_node": "score", "to_node": "rank"},
            {"from_node": "rank", "to_node": "roadmap"},
        ],
        "evals": ["PrioritizationLogic", "TimelineRealism", "StakeholderAlignment"],
    },
    {
        "id": "pm_release_notes",
        "name": "Release Notes Writer",
        "department": "product_management",
        "description": "Transform technical changelogs into user-friendly release notes",
        "nodes": [
            {
                "id": "parse",
                "prompt": "Parse this technical changelog and categorize changes: new features, improvements, bug fixes, breaking changes. Changelog: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "translate",
                "prompt": "Translate each technical change into user-benefit language. Focus on what users can now DO, not what was changed. Changes: {parse}",
                "model": "o3-pro",
                "role": "writer",
            },
            {
                "id": "compose",
                "prompt": "Compose release notes with: headline, highlights (top 3), full changelog, migration guide (if breaking changes). Content: {translate}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "parse", "to_node": "translate"},
            {"from_node": "translate", "to_node": "compose"},
        ],
        "evals": ["RequirementsCompleteness", "StakeholderAlignment"],
    },
]
