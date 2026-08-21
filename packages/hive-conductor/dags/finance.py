"""Finance DAGs — 5 multi-node pipelines for financial analysis."""

DAGS = [
    {
        "id": "fin_budget_variance",
        "name": "Budget Variance Analysis",
        "department": "finance",
        "description": "Analyze budget vs actual and explain variances",
        "nodes": [
            {
                "id": "parse",
                "prompt": "Parse budget and actual figures. Calculate variances (absolute and %). Flag items >10% variance. Input: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "explain",
                "prompt": "For each significant variance, provide root cause analysis: was it timing, volume, price, or one-time? Variances: {parse}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "report",
                "prompt": "Write variance report: executive summary, detailed analysis by category, corrective actions, and forecast impact. Analysis: {explain}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "parse", "to_node": "explain"},
            {"from_node": "explain", "to_node": "report"},
        ],
        "evals": ["NumericalAccuracy", "AssumptionTransparency", "DecisionClarity"],
    },
    {
        "id": "fin_investment_memo",
        "name": "Investment Memo",
        "department": "finance",
        "description": "Structured investment memo with risk analysis",
        "nodes": [
            {
                "id": "thesis",
                "prompt": "Develop investment thesis for: {input}. Include market opportunity, competitive advantage, and financial projections.",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "risks",
                "prompt": "Identify and quantify risks: market risk, execution risk, financial risk, regulatory risk. For each, estimate probability and impact. Thesis: {thesis}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "model",
                "prompt": "Build a simple financial model: revenue projections (3 years), key assumptions, sensitivity analysis on 2 variables. Context: {thesis}",
                "model": "claude-opus-4-6",
                "role": "modeler",
            },
            {
                "id": "memo",
                "prompt": "Write the investment memo: executive summary, thesis, financials, risks, recommendation (invest/pass/more diligence). All inputs: {model}\nRisks: {risks}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "thesis", "to_node": "risks"},
            {"from_node": "thesis", "to_node": "model"},
            {"from_node": "risks", "to_node": "memo"},
            {"from_node": "model", "to_node": "memo"},
        ],
        "evals": [
            "NumericalAccuracy",
            "RiskIdentification",
            "AssumptionTransparency",
            "DecisionClarity",
        ],
    },
    {
        "id": "fin_quarterly_forecast",
        "name": "Quarterly Forecast Model",
        "department": "finance",
        "description": "Build quarterly forecast from historical data and assumptions",
        "nodes": [
            {
                "id": "baseline",
                "prompt": "Establish baseline from historical data. Identify trends, seasonality, and growth rates. Data: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "assumptions",
                "prompt": "State forecast assumptions explicitly: growth rate, market conditions, headcount, pricing changes. Baseline: {baseline}",
                "model": "o3-pro",
                "role": "modeler",
            },
            {
                "id": "forecast",
                "prompt": "Generate quarterly forecast: revenue, costs, margins, cash flow. Include best/base/worst scenarios. Assumptions: {assumptions}",
                "model": "o3-pro",
                "role": "modeler",
            },
            {
                "id": "present",
                "prompt": "Format as board-ready forecast presentation: key numbers, charts descriptions, risks to forecast, and confidence level. Forecast: {forecast}",
                "model": "claude-opus-4-6",
                "role": "writer",
            },
        ],
        "edges": [
            {"from_node": "baseline", "to_node": "assumptions"},
            {"from_node": "assumptions", "to_node": "forecast"},
            {"from_node": "forecast", "to_node": "present"},
        ],
        "evals": ["NumericalAccuracy", "AssumptionTransparency", "RegulatoryCompliance"],
    },
    {
        "id": "fin_cost_benefit",
        "name": "Cost-Benefit Analysis",
        "department": "finance",
        "description": "Structured CBA for business decisions",
        "nodes": [
            {
                "id": "scope",
                "prompt": "Define the decision scope: what's being evaluated, alternatives, timeframe, and stakeholders. Decision: {input}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
            {
                "id": "quantify",
                "prompt": "Quantify all costs and benefits for each alternative. Include tangible and intangible. Use NPV where appropriate. Scope: {scope}",
                "model": "o3-pro",
                "role": "modeler",
            },
            {
                "id": "recommend",
                "prompt": "Compare alternatives, state the recommendation with confidence level, and identify what could change the answer. Analysis: {quantify}",
                "model": "claude-opus-4-6",
                "role": "analyst",
            },
        ],
        "edges": [
            {"from_node": "scope", "to_node": "quantify"},
            {"from_node": "quantify", "to_node": "recommend"},
        ],
        "evals": ["NumericalAccuracy", "DecisionClarity", "AssumptionTransparency"],
    },
    {
        "id": "fin_risk_assessment",
        "name": "Risk Assessment Report",
        "department": "finance",
        "description": "Comprehensive risk assessment with mitigation strategies",
        "nodes": [
            {
                "id": "identify",
                "prompt": "Identify all financial risks for: {input}. Categories: market, credit, operational, liquidity, regulatory.",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "assess",
                "prompt": "For each risk: estimate probability (1-5), impact (1-5), velocity, and current controls. Create risk matrix. Risks: {identify}",
                "model": "o3-pro",
                "role": "analyst",
            },
            {
                "id": "mitigate",
                "prompt": "For top 5 risks: propose mitigation strategies, cost of mitigation, residual risk after mitigation. Assessment: {assess}",
                "model": "claude-opus-4-6",
                "role": "strategist",
            },
        ],
        "edges": [
            {"from_node": "identify", "to_node": "assess"},
            {"from_node": "assess", "to_node": "mitigate"},
        ],
        "evals": ["RiskIdentification", "NumericalAccuracy", "DecisionClarity"],
    },
]
