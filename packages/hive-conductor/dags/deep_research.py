"""Deep Research DAGs — REAL research using web search tools.

Every research node calls web_search to get actual citations.
Analysis nodes work from those real citations.
No hallucinated sources. No fake data.
"""

DAGS = [
    {
        "id": "dr_market_analysis",
        "name": "Market Analysis Report",
        "department": "deep_research",
        "description": "Comprehensive market analysis from topic to actionable report",
        "nodes": [
            {
                "id": "scope",
                "prompt": 'Define 5 specific search queries that would gather comprehensive market data for: {input}. Include queries for market size, key players, trends, challenges, and opportunities. Output JSON: {"queries": [str]}',
                "model": "claude-opus-4-6",
                "role": "planner",
            },
            {
                "id": "search",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {"iterate_over": "scope.queries", "max_results": 5},
            },
            {
                "id": "synthesize",
                "prompt": "You have REAL search results with citations below. Synthesize them into structured market findings. ONLY use information from the provided citations. If a claim isn't supported by a citation, don't include it.\n\nSearch results:\n{search}\n\nOutput a markdown report with:\n- ## Market Size & Growth (cite sources)\n- ## Key Players (cite sources)\n- ## Trends (cite sources)\n- ## Challenges\n- ## Opportunities\n\nEvery factual claim MUST have a [Source: url] citation.",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "recommend",
                "prompt": "Based on this research (with real citations), provide 5 actionable recommendations. Each recommendation must reference specific data from the research. Do NOT invent statistics.\n\nResearch:\n{synthesize}",
                "model": "claude-opus-4-6",
                "role": "strategist",
            },
            {
                "id": "format",
                "prompt": "Format into a professional market analysis report in markdown. Preserve ALL citations from the research. Add:\n- Executive Summary (3 sentences)\n- ## sections with headers\n- ## Conclusion with key takeaways\n- ## References (list all cited URLs)\n\nContent:\n{recommend}\n\nOriginal research:\n{synthesize}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "scope", "to_node": "search"},
            {"from_node": "search", "to_node": "synthesize"},
            {"from_node": "synthesize", "to_node": "recommend"},
            {"from_node": "synthesize", "to_node": "format"},
            {"from_node": "recommend", "to_node": "format"},
        ],
        "evals": [
            "SourceAttribution",
            "ClaimFactuality",
            "Completeness",
            "Synthesis",
            "Actionability",
        ],
    },
    {
        "id": "dr_competitive_intel",
        "name": "Competitive Intelligence Brief",
        "department": "deep_research",
        "description": "Analyze real competitors using actual web data",
        "nodes": [
            {
                "id": "identify",
                "prompt": 'For the market: {input}, generate 5 search queries to find real competitor information — pricing pages, feature comparisons, recent news, funding rounds, customer reviews. Output JSON: {"queries": [str]}',
                "model": "claude-opus-4-6",
                "role": "planner",
            },
            {
                "id": "search",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {"iterate_over": "identify.queries", "max_results": 5},
            },
            {
                "id": "compare",
                "prompt": "Using ONLY the real search results below, create a competitive comparison matrix. Do NOT invent features or pricing — if the data isn't in the citations, say 'not found in sources'.\n\nSearch results:\n{search}\n\nCreate a comparison covering: positioning, pricing (if found), key features, recent moves. Cite every claim.",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "brief",
                "prompt": "Write a 2-page competitive intelligence brief from this real data. Include:\n- Key findings (with citations)\n- Threat assessment\n- Gaps/opportunities\n- Recommended counter-strategies\n\nData:\n{compare}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "identify", "to_node": "search"},
            {"from_node": "search", "to_node": "compare"},
            {"from_node": "compare", "to_node": "brief"},
        ],
        "evals": ["SourceAttribution", "Synthesis", "Actionability"],
    },
    {
        "id": "dr_tech_landscape",
        "name": "Technology Landscape Survey",
        "department": "deep_research",
        "description": "Survey real emerging technologies using actual sources",
        "nodes": [
            {
                "id": "queries",
                "prompt": 'For the technology area: {input}, generate 6 search queries to find: emerging tools, Gartner/Forrester reports, GitHub trending repos, recent conference talks, vendor comparisons, adoption case studies. Output JSON: {"queries": [str]}',
                "model": "claude-opus-4-6",
                "role": "planner",
            },
            {
                "id": "search",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {"iterate_over": "queries.queries", "max_results": 4},
            },
            {
                "id": "assess",
                "prompt": "From the REAL search results, assess each technology found. Rate readiness (1-5) based on actual evidence (GitHub stars, production deployments mentioned, enterprise adoption). Do NOT rate technologies you didn't find real data on.\n\nSearch results:\n{search}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "roadmap",
                "prompt": "Based on the evidence-backed assessment, create an adoption roadmap: what to adopt now (proven), pilot next quarter (promising), and watch (early). Every recommendation must cite the evidence.\n\nAssessment:\n{assess}",
                "model": "claude-opus-4-6",
                "role": "strategist",
            },
        ],
        "edges": [
            {"from_node": "queries", "to_node": "search"},
            {"from_node": "search", "to_node": "assess"},
            {"from_node": "assess", "to_node": "roadmap"},
        ],
        "evals": ["Completeness", "ClaimFactuality", "Actionability"],
    },
    {
        "id": "dr_regulatory_impact",
        "name": "Regulatory Impact Assessment",
        "department": "deep_research",
        "description": "Assess real regulatory changes using actual government/legal sources",
        "nodes": [
            {
                "id": "queries",
                "prompt": 'For the regulatory area: {input}, generate 5 search queries targeting: official government announcements, legal analysis articles, compliance guides, penalty/enforcement actions, industry response. Output JSON: {"queries": [str]}',
                "model": "claude-opus-4-6",
                "role": "planner",
            },
            {
                "id": "search",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {"iterate_over": "queries.queries", "max_results": 5},
            },
            {
                "id": "impact",
                "prompt": "From the REAL regulatory sources found, assess business impact. Only cite actual regulations, dates, and penalties found in the search results. If you can't find specific penalty amounts, say so.\n\nSearch results:\n{search}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "plan",
                "prompt": "Create a compliance action plan based on the real regulatory requirements identified. Cite specific regulations and deadlines found in the research.\n\nImpact assessment:\n{impact}",
                "model": "claude-opus-4-6",
                "role": "planner",
            },
        ],
        "edges": [
            {"from_node": "queries", "to_node": "search"},
            {"from_node": "search", "to_node": "impact"},
            {"from_node": "impact", "to_node": "plan"},
        ],
        "evals": ["ClaimFactuality", "Completeness", "Actionability"],
    },
    {
        "id": "dr_customer_insight",
        "name": "Customer Insight Synthesis",
        "department": "deep_research",
        "description": "Synthesize real customer data from reviews, forums, social media",
        "nodes": [
            {
                "id": "queries",
                "prompt": 'For the product/market: {input}, generate 5 search queries to find REAL customer feedback: product reviews, Reddit discussions, G2/Capterra reviews, Twitter complaints, support forum posts. Output JSON: {"queries": [str]}',
                "model": "claude-opus-4-6",
                "role": "planner",
            },
            {
                "id": "search",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {"iterate_over": "queries.queries", "max_results": 5},
            },
            {
                "id": "themes",
                "prompt": "From the REAL customer feedback found in search results, identify recurring themes. Quote actual customer language where possible. Do NOT invent customer quotes.\n\nSearch results:\n{search}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "actions",
                "prompt": "Translate the real customer insights into 5 specific product improvements. Each must reference actual customer pain points found in the research.\n\nInsights:\n{themes}",
                "model": "claude-opus-4-6",
                "role": "strategist",
            },
        ],
        "edges": [
            {"from_node": "queries", "to_node": "search"},
            {"from_node": "search", "to_node": "themes"},
            {"from_node": "themes", "to_node": "actions"},
        ],
        "evals": ["Synthesis", "Actionability", "Completeness"],
    },
]
