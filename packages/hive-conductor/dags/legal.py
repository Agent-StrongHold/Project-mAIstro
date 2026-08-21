"""Legal DAGs — 5 multi-node pipelines for legal document tasks."""

DAGS = [
    {
        "id": "legal_nda",
        "name": "NDA Generator",
        "department": "legal",
        "description": "Generate customized NDA from parameters",
        "nodes": [
            {
                "id": "params",
                "prompt": "Extract NDA parameters: parties, type (mutual/unilateral), duration, jurisdiction, carve-outs, and special terms. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "paralegal",
            },
            {
                "id": "draft",
                "prompt": "Draft NDA with: definitions, obligations, exclusions, term, remedies, and governing law. Use clear language. Parameters: {params}",
                "model": "o3-pro",
                "role": "attorney",
            },
            {
                "id": "review",
                "prompt": "Review for: completeness, ambiguity, enforceability, and balanced terms. Flag any one-sided clauses. Draft: {draft}",
                "model": "claude-opus-4-6",
                "role": "reviewer",
            },
        ],
        "edges": [
            {"from_node": "params", "to_node": "draft"},
            {"from_node": "draft", "to_node": "review"},
        ],
        "evals": ["ClauseCompleteness", "AmbiguityScore", "Jurisdiction"],
    },
    {
        "id": "legal_contract_summary",
        "name": "Contract Summary/Plain Language",
        "department": "legal",
        "description": "Translate complex contracts into plain language summaries",
        "nodes": [
            {
                "id": "parse",
                "prompt": "Parse contract into sections: parties, obligations, rights, term, termination, liability, and special clauses. Contract: {input}",
                "model": "o3-pro",
                "role": "paralegal",
            },
            {
                "id": "summarize",
                "prompt": "Write plain-language summary of each section. What does each party actually have to DO? What are the risks? Parsed: {parse}",
                "model": "o3-pro",
                "role": "attorney",
            },
            {
                "id": "flags",
                "prompt": "Flag concerning clauses: unusual terms, one-sided provisions, missing protections, and negotiation points. Summary: {summarize}",
                "model": "claude-opus-4-6",
                "role": "reviewer",
            },
        ],
        "edges": [
            {"from_node": "parse", "to_node": "summarize"},
            {"from_node": "summarize", "to_node": "flags"},
        ],
        "evals": ["PlainLanguage", "RiskExposure", "ClauseCompleteness"],
    },
    {
        "id": "legal_compliance_checklist",
        "name": "Compliance Checklist",
        "department": "legal",
        "description": "Generate compliance checklist for specific regulation",
        "nodes": [
            {
                "id": "identify",
                "prompt": "Identify applicable regulations and requirements for: {input}. Include federal, state, and industry-specific.",
                "model": "o3-pro",
                "role": "researcher",
            },
            {
                "id": "checklist",
                "prompt": "Create detailed compliance checklist: requirement, action needed, responsible party, deadline, evidence needed. Regulations: {identify}",
                "model": "o3-pro",
                "role": "attorney",
            },
            {
                "id": "prioritize",
                "prompt": "Prioritize by: penalty severity, deadline proximity, and implementation complexity. Add risk rating to each item. Checklist: {checklist}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
        ],
        "edges": [
            {"from_node": "identify", "to_node": "checklist"},
            {"from_node": "checklist", "to_node": "prioritize"},
        ],
        "evals": ["ClauseCompleteness", "Jurisdiction", "RiskExposure"],
    },
    {
        "id": "legal_tos",
        "name": "Terms of Service Drafter",
        "department": "legal",
        "description": "Draft terms of service for digital products",
        "nodes": [
            {
                "id": "scope",
                "prompt": "Define ToS scope: product type, user base, data handling, payment terms, and jurisdiction. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "paralegal",
            },
            {
                "id": "draft",
                "prompt": "Draft ToS sections: acceptance, user rights, prohibited use, IP, privacy reference, liability limitation, termination, disputes. Scope: {scope}",
                "model": "o3-pro",
                "role": "attorney",
            },
            {
                "id": "plain",
                "prompt": "Add plain-language summaries alongside legal text. Each section gets a 'In plain English:' sidebar. Draft: {draft}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "scope", "to_node": "draft"},
            {"from_node": "draft", "to_node": "plain"},
        ],
        "evals": ["PlainLanguage", "ClauseCompleteness", "AmbiguityScore"],
    },
    {
        "id": "legal_risk_clause",
        "name": "Risk Clause Identifier",
        "department": "legal",
        "description": "Identify and assess risky clauses in contracts",
        "nodes": [
            {
                "id": "scan",
                "prompt": "Scan this contract for high-risk clauses: unlimited liability, broad indemnification, non-compete, auto-renewal, unilateral changes. Contract: {input}",
                "model": "o3-pro",
                "role": "attorney",
            },
            {
                "id": "assess",
                "prompt": "For each risky clause: explain the risk, rate severity (1-5), suggest alternative language, and note negotiation leverage. Clauses: {scan}",
                "model": "o3-pro",
                "role": "attorney",
            },
            {
                "id": "report",
                "prompt": "Write risk report: executive summary, clause-by-clause analysis, overall risk rating, and recommended actions (sign/negotiate/reject). Assessment: {assess}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "scan", "to_node": "assess"},
            {"from_node": "assess", "to_node": "report"},
        ],
        "evals": ["RiskExposure", "AmbiguityScore", "PlainLanguage"],
    },
]
