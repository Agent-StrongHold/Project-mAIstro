"""Press Releases DAGs — based on REAL news events and documents.

Every PR starts by searching for actual news events, real company data,
and real quotes. No fabricated documents or fake announcements.
"""

DAGS = [
    {
        "id": "pr_product_launch",
        "name": "Product Launch Announcement",
        "department": "press_releases",
        "description": "Full press release for a product launch — grounded in real data",
        "nodes": [
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} product launch announcement",
                    "max_results": 5,
                },
            },
            {
                "id": "facts",
                "prompt": "From the REAL search results below, extract verifiable facts for a press release: company name, product name, features mentioned, pricing if found, launch date, executive names/titles, and any real quotes.\n\nIf information is NOT in the sources, mark it as '[TO BE PROVIDED]' — do NOT invent it.\n\nSearch results:\n{research}\n\nOriginal topic:\n{input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "draft",
                "prompt": "Write a press release in AP style using ONLY the verified facts below. Where facts are marked '[TO BE PROVIDED]', use realistic placeholders clearly marked.\n\nStructure: dateline, lead (who/what/when/where/why), body, quote, background, boilerplate.\n\nVerified facts:\n{facts}",
                "model": "o3-pro",
                "role": "writer",
            },
            {
                "id": "verify",
                "prompt": "Fact-check this press release against the original sources. Flag any claim that isn't supported by the research. Ensure:\n- No fabricated quotes\n- No invented statistics\n- Dates match sources\n- Company/product names are spelled correctly\n\nDraft:\n{draft}\nOriginal sources:\n{research}",
                "model": "claude-opus-4-6",
                "role": "editor",
            },
        ],
        "edges": [
            {"from_node": "research", "to_node": "facts"},
            {"from_node": "facts", "to_node": "draft"},
            {"from_node": "draft", "to_node": "verify"},
            {"from_node": "research", "to_node": "verify"},
        ],
        "evals": [
            "InvertedPyramid",
            "QuoteQuality",
            "APStyle",
            "FactualAccuracy",
            "Newsworthiness",
        ],
    },
    {
        "id": "pr_partnership",
        "name": "Partnership/Collaboration Announcement",
        "department": "press_releases",
        "description": "Announce a partnership — grounded in real company data",
        "nodes": [
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} partnership collaboration announcement",
                    "max_results": 5,
                },
            },
            {
                "id": "context",
                "prompt": "From search results, extract: both companies' real descriptions, their actual executives (names + titles), what they actually do, and any real details about the partnership.\n\nMark anything not found as '[NEEDS VERIFICATION]'.\n\nSearch results:\n{research}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "draft",
                "prompt": "Write a partnership press release using only verified information. Include quotes attributed to real executives found in research. Balance both companies equally.\n\nContext:\n{context}",
                "model": "o3-pro",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "research", "to_node": "context"},
            {"from_node": "context", "to_node": "draft"},
        ],
        "evals": ["QuoteQuality", "FactualAccuracy", "APStyle"],
    },
    {
        "id": "pr_executive",
        "name": "Executive Appointment",
        "department": "press_releases",
        "description": "Announce a new executive — using real biographical data",
        "nodes": [
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} executive biography LinkedIn",
                    "max_results": 5,
                },
            },
            {
                "id": "bio",
                "prompt": "From search results, extract REAL biographical data: actual previous roles, real companies worked at, education if found, notable achievements that are verifiable.\n\nDo NOT invent career history. Mark gaps as '[BIO DETAIL NEEDED]'.\n\nSearch results:\n{research}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "draft",
                "prompt": "Write executive appointment press release using only verified bio data. Include:\n- Announcement with real role title\n- CEO quote (mark as [QUOTE NEEDED] if no real CEO name found)\n- New exec quote about vision\n- Bio paragraph from verified data only\n- Company boilerplate\n\nBio:\n{bio}",
                "model": "o3-pro",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "research", "to_node": "bio"},
            {"from_node": "bio", "to_node": "draft"},
        ],
        "evals": ["QuoteQuality", "FactualAccuracy", "APStyle", "InvertedPyramid"],
    },
    {
        "id": "pr_earnings",
        "name": "Earnings/Financial Results",
        "department": "press_releases",
        "description": "Quarterly results — using real financial data from sources",
        "nodes": [
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} quarterly earnings results revenue",
                    "max_results": 5,
                },
            },
            {
                "id": "numbers",
                "prompt": "Extract REAL financial figures from search results: revenue, growth %, EPS, guidance, key metrics. Every number must have a source URL.\n\nIf a number isn't in the sources, do NOT include it.\n\nSearch results:\n{research}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "draft",
                "prompt": "Write earnings press release using ONLY the verified numbers. Include safe harbor statement. Every financial claim must be traceable to the research.\n\nVerified numbers:\n{numbers}",
                "model": "o3-pro",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "research", "to_node": "numbers"},
            {"from_node": "numbers", "to_node": "draft"},
        ],
        "evals": ["FactualAccuracy", "APStyle", "Newsworthiness"],
    },
    {
        "id": "pr_crisis",
        "name": "Crisis Communication Statement",
        "department": "press_releases",
        "description": "Rapid response — grounded in real incident details",
        "nodes": [
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} incident response statement",
                    "max_results": 5,
                },
            },
            {
                "id": "assess",
                "prompt": "From search results, extract ONLY verified facts about the incident: what happened, when, who's affected, what's confirmed vs rumored. Clearly separate CONFIRMED from UNCONFIRMED.\n\nSearch results:\n{research}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "draft",
                "prompt": "Write crisis statement using ONLY confirmed facts. Rules:\n- Acknowledge only what's confirmed\n- Express concern without admitting liability\n- State concrete actions being taken\n- No speculation\n- Provide contact for updates\n\nConfirmed facts:\n{assess}",
                "model": "o3-pro",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "research", "to_node": "assess"},
            {"from_node": "assess", "to_node": "draft"},
        ],
        "evals": ["FactualAccuracy", "APStyle", "QuoteQuality"],
    },
]
