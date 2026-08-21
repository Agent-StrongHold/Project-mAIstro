"""HR/People Ops DAGs — 5 multi-node pipelines for HR tasks."""

DAGS = [
    {
        "id": "hr_job_description",
        "name": "Job Description Generator",
        "department": "hr_people_ops",
        "description": "Generate inclusive, compliant job descriptions",
        "nodes": [
            {
                "id": "requirements",
                "prompt": "Extract role requirements from: {input}. Separate must-haves from nice-to-haves. Identify level and team.",
                "model": "claude-opus-4-6",
                "role": "recruiter",
            },
            {
                "id": "draft",
                "prompt": "Write job description: title, about us, role summary, responsibilities, qualifications, benefits. Use inclusive language. Requirements: {requirements}",
                "model": "o3-pro",
                "role": "writer",
            },
            {
                "id": "compliance",
                "prompt": "Review for legal compliance: no discriminatory language, proper EEO statement, reasonable qualifications, ADA compliance. Draft: {draft}",
                "model": "claude-opus-4-6",
                "role": "reviewer",
            },
        ],
        "edges": [
            {"from_node": "requirements", "to_node": "draft"},
            {"from_node": "draft", "to_node": "compliance"},
        ],
        "evals": ["LegalCompliance", "ToneAppropriateness", "HRActionability"],
    },
    {
        "id": "hr_performance_review",
        "name": "Performance Review Summary",
        "department": "hr_people_ops",
        "description": "Structured performance review from raw feedback",
        "nodes": [
            {
                "id": "gather",
                "prompt": "Organize performance data: achievements, areas for growth, peer feedback themes, and goal progress. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "assess",
                "prompt": "Write balanced assessment: strengths with examples, development areas with specific behaviors, and overall rating justification. Data: {gather}",
                "model": "o3-pro",
                "role": "manager",
            },
            {
                "id": "plan",
                "prompt": "Create development plan: 3 goals for next period, resources needed, check-in schedule, and success metrics. Assessment: {assess}",
                "model": "claude-opus-4-6",
                "role": "coach",
            },
        ],
        "edges": [
            {"from_node": "gather", "to_node": "assess"},
            {"from_node": "assess", "to_node": "plan"},
        ],
        "evals": ["ToneAppropriateness", "HRActionability", "Confidentiality"],
    },
    {
        "id": "hr_policy_update",
        "name": "Policy Update Communication",
        "department": "hr_people_ops",
        "description": "Communicate policy changes clearly and empathetically",
        "nodes": [
            {
                "id": "analyze",
                "prompt": "Analyze the policy change: what's changing, why, who's affected, effective date, and what employees need to do. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "draft",
                "prompt": "Write employee communication: clear explanation, rationale, impact, FAQs, and where to get help. Keep tone supportive. Analysis: {analyze}",
                "model": "o3-pro",
                "role": "writer",
            },
            {
                "id": "review",
                "prompt": "Review for: legal accuracy, tone appropriateness, completeness of information, and clear action items. Draft: {draft}",
                "model": "claude-opus-4-6",
                "role": "reviewer",
            },
        ],
        "edges": [
            {"from_node": "analyze", "to_node": "draft"},
            {"from_node": "draft", "to_node": "review"},
        ],
        "evals": ["PolicyAccuracy", "ToneAppropriateness", "LegalCompliance"],
    },
    {
        "id": "hr_onboarding",
        "name": "Onboarding Checklist Generator",
        "department": "hr_people_ops",
        "description": "Personalized onboarding plan for new hires",
        "nodes": [
            {
                "id": "profile",
                "prompt": "Build new hire profile: role, level, team, start date, manager, required tools/access. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "coordinator",
            },
            {
                "id": "checklist",
                "prompt": "Generate onboarding checklist: pre-day-1, week 1, week 2-4, month 2-3. Include IT setup, meetings, training, and milestones. Profile: {profile}",
                "model": "o3-pro",
                "role": "planner",
            },
            {
                "id": "personalize",
                "prompt": "Personalize: add role-specific training, team introductions, and 30-60-90 day goals. Checklist: {checklist}",
                "model": "claude-opus-4-6",
                "role": "coordinator",
            },
        ],
        "edges": [
            {"from_node": "profile", "to_node": "checklist"},
            {"from_node": "checklist", "to_node": "personalize"},
        ],
        "evals": ["HRActionability", "PolicyAccuracy", "ToneAppropriateness"],
    },
    {
        "id": "hr_exit_interview",
        "name": "Exit Interview Synthesis",
        "department": "hr_people_ops",
        "description": "Synthesize exit interview data into actionable insights",
        "nodes": [
            {
                "id": "themes",
                "prompt": "Identify recurring themes from exit interview responses: reasons for leaving, satisfaction areas, improvement suggestions. Data: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "insights",
                "prompt": "Synthesize themes into actionable insights: what's driving attrition, which teams are affected, and what interventions could help. Themes: {themes}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "report",
                "prompt": "Write confidential report for leadership: key findings, trend data, recommended actions with priority and owner. Insights: {insights}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "themes", "to_node": "insights"},
            {"from_node": "insights", "to_node": "report"},
        ],
        "evals": ["Confidentiality", "HRActionability", "ToneAppropriateness"],
    },
]
