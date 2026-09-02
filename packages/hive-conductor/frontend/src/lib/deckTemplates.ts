export const DECK_TEMPLATES = [
  { name: "🎯 Hero KPI", html: `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);border-radius:24px;padding:3rem">
<p style="font-size:0.8rem;text-transform:uppercase;letter-spacing:0.2em;color:#a78bfa;margin-bottom:1rem;font-weight:600">Portfolio Snapshot</p>
<p style="font-size:6rem;font-weight:900;background:linear-gradient(135deg,#a78bfa,#c4a661);-webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1">152</p>
<p style="font-size:1.4rem;color:#e8e8f0;margin-top:0.5rem;font-weight:500">Active Use Cases</p>
<div style="display:flex;gap:2.5rem;margin-top:2.5rem">
<div style="text-align:center"><p style="font-size:2.2rem;font-weight:800;color:#22c55e">74%</p><p style="font-size:0.75rem;color:#8b83a8;margin-top:4px">In Development</p></div>
<div style="text-align:center"><p style="font-size:2.2rem;font-weight:800;color:#0ea5e9">24</p><p style="font-size:0.75rem;color:#8b83a8;margin-top:4px">In v2 Pipeline</p></div>
<div style="text-align:center"><p style="font-size:2.2rem;font-weight:800;color:#f59e0b">9</p><p style="font-size:0.75rem;color:#8b83a8;margin-top:4px">Commercialized</p></div>
</div></div>` },

  { name: "📊 Status Funnel", html: `<div style="padding:2.5rem;height:100%;background:#0a0914;display:flex;flex-direction:column;justify-content:center">
<h2 style="font-family:Georgia,serif;font-size:1.8rem;margin-bottom:0.3rem;color:#f3f0fb">Lifecycle Funnel</h2>
<p style="font-size:0.8rem;color:#8b83a8;margin-bottom:2rem">Use cases by stage — data from Airtable, live</p>
<div style="display:flex;flex-direction:column;gap:12px">
<div style="display:flex;align-items:center;gap:12px"><span style="width:160px;font-size:0.8rem;color:#c4b5fd">Development</span><div style="flex:1;height:32px;background:rgba(139,92,246,0.12);border-radius:8px;overflow:hidden"><div style="width:74%;height:100%;background:linear-gradient(90deg,#6366f1,#8b5cf6);border-radius:8px;display:flex;align-items:center;padding-left:12px;font-size:0.75rem;font-weight:700;color:#fff">109</div></div></div>
<div style="display:flex;align-items:center;gap:12px"><span style="width:160px;font-size:0.8rem;color:#c4b5fd">Comm. Request</span><div style="flex:1;height:32px;background:rgba(139,92,246,0.12);border-radius:8px;overflow:hidden"><div style="width:22%;height:100%;background:linear-gradient(90deg,#ec4899,#f43f5e);border-radius:8px;display:flex;align-items:center;padding-left:12px;font-size:0.75rem;font-weight:700;color:#fff">17</div></div></div>
<div style="display:flex;align-items:center;gap:12px"><span style="width:160px;font-size:0.8rem;color:#c4b5fd">Commercialized</span><div style="flex:1;height:32px;background:rgba(139,92,246,0.12);border-radius:8px;overflow:hidden"><div style="width:12%;height:100%;background:linear-gradient(90deg,#10b981,#22c55e);border-radius:8px;display:flex;align-items:center;padding-left:12px;font-size:0.75rem;font-weight:700;color:#fff">9</div></div></div>
<div style="display:flex;align-items:center;gap:12px"><span style="width:160px;font-size:0.8rem;color:#c4b5fd">Proposal</span><div style="flex:1;height:32px;background:rgba(139,92,246,0.12);border-radius:8px;overflow:hidden"><div style="width:9%;height:100%;background:linear-gradient(90deg,#f59e0b,#fbbf24);border-radius:8px;display:flex;align-items:center;padding-left:12px;font-size:0.75rem;font-weight:700;color:#fff">7</div></div></div>
<div style="display:flex;align-items:center;gap:12px"><span style="width:160px;font-size:0.8rem;color:#c4b5fd">OTE Review</span><div style="flex:1;height:32px;background:rgba(139,92,246,0.12);border-radius:8px;overflow:hidden"><div style="width:7%;height:100%;background:linear-gradient(90deg,#06b6d4,#22d3ee);border-radius:8px;display:flex;align-items:center;padding-left:12px;font-size:0.75rem;font-weight:700;color:#fff">5</div></div></div>
</div></div>` },

  { name: "🍩 Category Mix", html: `<div style="display:flex;align-items:center;justify-content:center;height:100%;gap:3rem;background:linear-gradient(180deg,#0a0914 0%,#11101e 100%);padding:3rem">
<svg viewBox="0 0 120 120" width="220" height="220">
<circle cx="60" cy="60" r="48" fill="none" stroke="#6366f1" stroke-width="18" stroke-dasharray="175 301" stroke-dashoffset="0" transform="rotate(-90 60 60)"/>
<circle cx="60" cy="60" r="48" fill="none" stroke="#ec4899" stroke-width="18" stroke-dasharray="85 301" stroke-dashoffset="-175" transform="rotate(-90 60 60)"/>
<circle cx="60" cy="60" r="48" fill="none" stroke="#f59e0b" stroke-width="18" stroke-dasharray="41 301" stroke-dashoffset="-260" transform="rotate(-90 60 60)"/>
<text x="60" y="56" text-anchor="middle" fill="#f3f0fb" font-size="18" font-weight="800">152</text>
<text x="60" y="72" text-anchor="middle" fill="#8b83a8" font-size="8" text-transform="uppercase">use cases</text>
</svg>
<div style="display:flex;flex-direction:column;gap:14px">
<div style="display:flex;align-items:center;gap:10px"><span style="width:12px;height:12px;border-radius:50%;background:#6366f1"></span><span style="font-size:1rem;color:#e8e8f0;font-weight:600">Automations & Agents</span><span style="margin-left:auto;font-size:1.1rem;font-weight:800;color:#f3f0fb">58%</span></div>
<div style="display:flex;align-items:center;gap:10px"><span style="width:12px;height:12px;border-radius:50%;background:#ec4899"></span><span style="font-size:1rem;color:#e8e8f0;font-weight:600">Human Enhancement</span><span style="margin-left:auto;font-size:1.1rem;font-weight:800;color:#f3f0fb">28%</span></div>
<div style="display:flex;align-items:center;gap:10px"><span style="width:12px;height:12px;border-radius:50%;background:#f59e0b"></span><span style="font-size:1rem;color:#e8e8f0;font-weight:600">Data Analysis</span><span style="margin-left:auto;font-size:1.1rem;font-weight:800;color:#f3f0fb">14%</span></div>
</div></div>` },

  { name: "📈 Migration Progress", html: `<div style="padding:3rem;height:100%;background:linear-gradient(135deg,#0c1222,#0f172a);display:flex;flex-direction:column;justify-content:center">
<h2 style="font-family:Georgia,serif;font-size:1.8rem;color:#f3f0fb;margin-bottom:0.3rem">Platform v2 Migration</h2>
<p style="font-size:0.8rem;color:#64748b;margin-bottom:2rem">Pipeline progress toward full platform migration</p>
<div style="display:flex;gap:1.5rem;margin-bottom:2rem">
<div style="flex:1;background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);border-radius:12px;padding:1.2rem;text-align:center"><p style="font-size:2.4rem;font-weight:800;color:#818cf8">24</p><p style="font-size:0.7rem;color:#94a3b8;margin-top:4px">In Pipeline</p></div>
<div style="flex:1;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:12px;padding:1.2rem;text-align:center"><p style="font-size:2.4rem;font-weight:800;color:#34d399">20</p><p style="font-size:0.7rem;color:#94a3b8;margin-top:4px">Active Migration</p></div>
<div style="flex:1;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:12px;padding:1.2rem;text-align:center"><p style="font-size:2.4rem;font-weight:800;color:#fbbf24">3</p><p style="font-size:0.7rem;color:#94a3b8;margin-top:4px">Migrated</p></div>
</div>
<div style="height:12px;background:rgba(255,255,255,0.05);border-radius:6px;overflow:hidden;display:flex">
<div style="width:50%;background:linear-gradient(90deg,#6366f1,#818cf8);border-radius:6px"></div>
<div style="width:42%;background:linear-gradient(90deg,#10b981,#34d399)"></div>
<div style="width:8%;background:linear-gradient(90deg,#f59e0b,#fbbf24)"></div>
</div>
<p style="font-size:0.7rem;color:#64748b;margin-top:8px;text-align:right">47 total in v2 cohort</p>
</div>` },

  { name: "👥 PM Load", html: `<div style="padding:3rem;height:100%;background:#0a0914;display:flex;flex-direction:column;justify-content:center">
<h2 style="font-family:Georgia,serif;font-size:1.8rem;color:#f3f0fb;margin-bottom:2rem">PM Workload Distribution</h2>
<div style="display:flex;flex-direction:column;gap:10px">
<div style="display:flex;align-items:center;gap:12px"><div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:700;color:#fff">1</div><span style="flex:1;font-size:0.95rem;color:#e8e8f0">Prashant Chopde</span><div style="width:200px;height:8px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden"><div style="width:59%;height:100%;background:#6366f1;border-radius:4px"></div></div><span style="font-size:0.85rem;font-weight:700;color:#a78bfa;width:30px;text-align:right">39</span></div>
<div style="display:flex;align-items:center;gap:12px"><div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#ec4899,#f43f5e);display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:700;color:#fff">2</div><span style="flex:1;font-size:0.95rem;color:#e8e8f0">Anthony Mitchell</span><div style="width:200px;height:8px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden"><div style="width:33%;height:100%;background:#ec4899;border-radius:4px"></div></div><span style="font-size:0.85rem;font-weight:700;color:#ec4899;width:30px;text-align:right">22</span></div>
<div style="display:flex;align-items:center;gap:12px"><div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#f59e0b,#fbbf24);display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:700;color:#fff">3</div><span style="flex:1;font-size:0.95rem;color:#e8e8f0">Ivan Castro</span><div style="width:200px;height:8px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden"><div style="width:9%;height:100%;background:#f59e0b;border-radius:4px"></div></div><span style="font-size:0.85rem;font-weight:700;color:#f59e0b;width:30px;text-align:right">6</span></div>
</div></div>` },

  { name: "📋 Record List", html: `<div style="padding:3rem;height:100%;background:linear-gradient(180deg,#0f0c29,#1a1640);display:flex;flex-direction:column;justify-content:center">
<h2 style="font-family:Georgia,serif;font-size:1.6rem;color:#f3f0fb;margin-bottom:0.5rem">Closest to Migration</h2>
<p style="font-size:0.75rem;color:#8b83a8;margin-bottom:1.5rem">Onboarding + Testing — ball in users' court</p>
<div style="display:flex;flex-direction:column;gap:8px">
<div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);border-radius:8px"><span style="width:8px;height:8px;border-radius:50%;background:#22c55e;flex-shrink:0"></span><span style="font-size:0.85rem;color:#e8e8f0">AI-Powered Survey QA Evaluator</span><span style="margin-left:auto;font-size:0.65rem;color:#8b83a8;background:rgba(139,92,246,0.15);padding:2px 8px;border-radius:4px">Testing</span></div>
<div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);border-radius:8px"><span style="width:8px;height:8px;border-radius:50%;background:#22c55e;flex-shrink:0"></span><span style="font-size:0.85rem;color:#e8e8f0">RAG Chatbot for Incentive Queries</span><span style="margin-left:auto;font-size:0.65rem;color:#8b83a8;background:rgba(139,92,246,0.15);padding:2px 8px;border-radius:4px">Testing</span></div>
<div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);border-radius:8px"><span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;flex-shrink:0"></span><span style="font-size:0.85rem;color:#e8e8f0">MOCA Agent</span><span style="margin-left:auto;font-size:0.65rem;color:#8b83a8;background:rgba(245,158,11,0.15);padding:2px 8px;border-radius:4px">Onboarding</span></div>
<div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);border-radius:8px"><span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;flex-shrink:0"></span><span style="font-size:0.85rem;color:#e8e8f0">DCL Revenue Management AI Email</span><span style="margin-left:auto;font-size:0.65rem;color:#8b83a8;background:rgba(245,158,11,0.15);padding:2px 8px;border-radius:4px">Onboarding</span></div>
</div></div>` },

  { name: "✨ Title Slide", html: `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;background:linear-gradient(135deg,#0f0c29 0%,#302b63 50%,#24243e 100%);text-align:center;padding:4rem">
<p style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.3em;color:#a78bfa;margin-bottom:1.5rem;font-weight:600">Platform · OKR Review</p>
<h1 style="font-size:3.2rem;font-family:Georgia,serif;font-weight:700;color:#f3f0fb;line-height:1.2;max-width:18ch">Use Case Portfolio Health</h1>
<p style="font-size:1.1rem;color:#8b83a8;margin-top:1.5rem;max-width:40ch;line-height:1.6">Live data from Airtable · Refreshed every 60 seconds</p>
<div style="margin-top:3rem;display:flex;gap:8px"><span style="width:40px;height:4px;border-radius:2px;background:#a78bfa"></span><span style="width:40px;height:4px;border-radius:2px;background:rgba(167,139,250,0.3)"></span><span style="width:40px;height:4px;border-radius:2px;background:rgba(167,139,250,0.3)"></span></div>
</div>` },

  { name: "🙏 Thank You", html: `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;background:linear-gradient(135deg,#0f0c29,#1a1640);text-align:center;padding:4rem">
<p style="font-size:4rem;margin-bottom:1rem">🐝</p>
<h1 style="font-size:2.5rem;font-family:Georgia,serif;color:#f3f0fb">Thank You</h1>
<p style="font-size:1rem;color:#8b83a8;margin-top:1rem;max-width:35ch;line-height:1.6">Questions, feedback, or ideas — reach out anytime</p>
<div style="margin-top:2.5rem;padding:12px 24px;border:1px solid rgba(167,139,250,0.3);border-radius:8px;font-size:0.8rem;color:#a78bfa">pm@example.com</div>
</div>` },
] as const;
