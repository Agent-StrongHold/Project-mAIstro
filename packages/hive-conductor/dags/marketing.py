"""Marketing DAGs — 5 multi-node pipelines for marketing tasks."""

DAGS = [
    {
        "id": "mkt_campaign_brief",
        "name": "Campaign Brief Generator",
        "department": "marketing",
        "description": "Full campaign brief from business objective",
        "nodes": [
            {
                "id": "objective",
                "prompt": "Define campaign objective, target audience, budget, and timeline from: {input}. Include success metrics.",
                "model": "claude-opus-4-6",
                "role": "strategist",
            },
            {
                "id": "strategy",
                "prompt": "Develop campaign strategy: messaging framework, channels, content types, and phasing. Objective: {objective}",
                "model": "o3-pro",
                "role": "strategist",
            },
            {
                "id": "brief",
                "prompt": "Write the campaign brief: background, objective, audience, key message, channels, timeline, budget allocation, KPIs. Strategy: {strategy}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "objective", "to_node": "strategy"},
            {"from_node": "strategy", "to_node": "brief"},
        ],
        "evals": ["AudienceTargeting", "Measurability", "ChannelFit"],
    },
    {
        "id": "mkt_social_calendar",
        "name": "Social Media Content Calendar",
        "department": "marketing",
        "description": "Week of social content across platforms",
        "nodes": [
            {
                "id": "themes",
                "prompt": "Identify content themes and hooks for: {input}. Consider trending topics, brand pillars, and audience interests.",
                "model": "claude-opus-4-6",
                "role": "strategist",
            },
            {
                "id": "calendar",
                "prompt": "Create a 5-day content calendar: platform, post type, copy, hashtags, best time to post. Mix educational, entertaining, and promotional. Themes: {themes}",
                "model": "o3-pro",
                "role": "creator",
            },
            {
                "id": "optimize",
                "prompt": "Optimize each post: tighten copy, improve hooks, add CTAs, ensure platform-specific formatting (character limits, hashtag counts). Calendar: {calendar}",
                "model": "claude-opus-4-6",
                "role": "editor",
            },
        ],
        "edges": [
            {"from_node": "themes", "to_node": "calendar"},
            {"from_node": "calendar", "to_node": "optimize"},
        ],
        "evals": ["ChannelFit", "CTAClarity", "BrandVoice"],
    },
    {
        "id": "mkt_email_sequence",
        "name": "Email Sequence Writer",
        "department": "marketing",
        "description": "Multi-email nurture sequence",
        "nodes": [
            {
                "id": "journey",
                "prompt": "Map the email journey: trigger, goal, number of emails, spacing, and progression logic. Context: {input}",
                "model": "claude-opus-4-6",
                "role": "strategist",
            },
            {
                "id": "write",
                "prompt": "Write each email: subject line, preview text, body, CTA. Vary tone from educational to promotional. Journey: {journey}",
                "model": "o3-pro",
                "role": "copywriter",
            },
            {
                "id": "optimize",
                "prompt": "Optimize: A/B subject line variants, improve open-rate hooks, ensure mobile-friendly length, add personalization tokens. Emails: {write}",
                "model": "claude-opus-4-6",
                "role": "optimizer",
            },
        ],
        "edges": [
            {"from_node": "journey", "to_node": "write"},
            {"from_node": "write", "to_node": "optimize"},
        ],
        "evals": ["CTAClarity", "AudienceTargeting", "Measurability"],
    },
    {
        "id": "mkt_landing_page",
        "name": "Landing Page Copy",
        "department": "marketing",
        "description": "High-converting landing page copy",
        "nodes": [
            {
                "id": "research",
                "prompt": "Research the offer and audience: unique value prop, objections to overcome, social proof available, competitive positioning. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "researcher",
            },
            {
                "id": "wireframe",
                "prompt": "Create copy wireframe: hero headline, subhead, benefits (3-5), social proof section, FAQ, and CTA. Research: {research}",
                "model": "o3-pro",
                "role": "copywriter",
            },
            {
                "id": "write",
                "prompt": "Write full landing page copy for each section. Focus on benefits over features, use power words, create urgency. Wireframe: {wireframe}",
                "model": "o3-pro",
                "role": "copywriter",
            },
            {
                "id": "cro",
                "prompt": "Apply CRO best practices: above-fold CTA, reduce friction, add trust signals, optimize for scanning. Copy: {write}",
                "model": "claude-opus-4-6",
                "role": "optimizer",
            },
        ],
        "edges": [
            {"from_node": "research", "to_node": "wireframe"},
            {"from_node": "wireframe", "to_node": "write"},
            {"from_node": "write", "to_node": "cro"},
        ],
        "evals": ["CTAClarity", "BrandVoice", "AudienceTargeting"],
    },
    {
        "id": "mkt_brand_enforcer",
        "name": "Brand Guidelines Enforcer",
        "department": "marketing",
        "description": "Review content against brand guidelines",
        "nodes": [
            {
                "id": "extract",
                "prompt": "Extract brand guidelines context: voice, tone, do/don't, color references, terminology. Guidelines: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "audit",
                "prompt": "Audit the content against brand guidelines. Flag violations with specific line references and severity. Content to audit: {input}\nGuidelines: {extract}",
                "model": "o3-pro",
                "role": "reviewer",
            },
            {
                "id": "fix",
                "prompt": "Rewrite flagged sections to comply with brand guidelines while preserving the message intent. Audit: {audit}",
                "model": "claude-opus-4-6",
                "role": "editor",
            },
        ],
        "edges": [
            {"from_node": "extract", "to_node": "audit"},
            {"from_node": "audit", "to_node": "fix"},
        ],
        "evals": ["BrandVoice", "ChannelFit", "CTAClarity"],
    },
]
