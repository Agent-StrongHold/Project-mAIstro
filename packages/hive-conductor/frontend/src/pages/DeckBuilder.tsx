import { useState, useRef, useCallback, useEffect } from "react";

const C = { bg: "#0a0914", card: "#11101e", border: "rgba(196,166,97,0.14)", gold: "#c4a661", ink: "#f3f0fb", muted: "#8b83a8", dim: "#5a5478", acc: "#a78bfa", danger: "#e87c7c" };

interface Slide { id: string; html: string; notes: string; }

function uid() { return Math.random().toString(36).slice(2, 10); }

const BLANK_SLIDE: () => Slide = () => ({ id: uid(), html: "<h1>Title</h1><p>Content</p>", notes: "" });

const TEMPLATES = [
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
];

function DeckChat({ slides, onUpdateSlides, activeIdx }: { slides: Slide[]; onUpdateSlides: (s: Slide[]) => void; activeIdx: number }) {
  const [value, setValue] = useState("");
  const [msgs, setMsgs] = useState<{ role: string; content: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [msgs]);

  const submit = async () => {
    if (!value.trim() || loading) return;
    const userMsg = value.trim();
    setValue("");
    setMsgs(m => [...m, { role: "user", content: userMsg }]);
    setLoading(true);
    try {
      const contextPrefix = `[DECK CONTEXT: ${slides.length} slides, active=#${activeIdx + 1}. I want stunning presentation slides with gradients, big numbers, SVG charts where relevant to the topic. Wrap each slide in <slide> tags. Use dark backgrounds, color:#a78bfa accents.]\n\n`;
      const r = await fetch("/v1/chat/complete", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [
            ...msgs.slice(-6),
            { role: "user", content: contextPrefix + userMsg },
          ],
        }),
      });
      const data = await r.json();
      const reply = data?.choices?.[0]?.message?.content || data?.content || "No response";
      setMsgs(m => [...m, { role: "assistant", content: reply }]);

      // Parse <slide> tags from response and apply them
      const slideMatches = [...reply.matchAll(/<slide(?:\s+index="(\d+)")?>([\s\S]*?)<\/slide>/gi)];
      if (slideMatches.length > 0) {
        const newSlides = [...slides];
        for (const match of slideMatches) {
          const idx = match[1] ? parseInt(match[1]) - 1 : -1;
          const html = match[2].trim();
          if (idx >= 0 && idx < newSlides.length) {
            newSlides[idx] = { ...newSlides[idx], html };
          } else {
            newSlides.push({ id: uid(), html, notes: "" });
          }
        }
        onUpdateSlides(newSlides);
      }
    } catch {
      setMsgs(m => [...m, { role: "assistant", content: "Connection error — check that the backend is running." }]);
    }
    setLoading(false);
  };

  return (
    <div style={{ borderTop: `1px solid ${C.border}`, marginTop: "1rem", paddingTop: "0.75rem" }}>
      {msgs.length > 0 && (
        <div ref={ref} style={{ maxHeight: 150, overflowY: "auto", marginBottom: 8, display: "flex", flexDirection: "column", gap: 4 }}>
          {msgs.slice(-6).map((m, i) => (
            <div key={i} style={{ fontSize: "0.65rem", color: m.role === "user" ? C.gold : C.muted, lineHeight: 1.4 }}>
              <span style={{ fontWeight: 600 }}>{m.role === "user" ? "You" : "✦"}: </span>
              {m.content.replace(/<slide[^>]*>[\s\S]*?<\/slide>/gi, "[slide generated]").slice(0, 200)}
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 6 }}>
        <input value={value} onChange={e => setValue(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          placeholder="✦ Describe slides to generate, or ask to edit..."
          style={{ flex: 1, background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 12px", color: C.ink, fontSize: "0.72rem", outline: "none" }} />
        <button onClick={submit} disabled={loading} style={{ padding: "8px 14px", borderRadius: 8, border: "none", background: C.acc, color: "#fff", fontSize: "0.68rem", fontWeight: 600, cursor: "pointer", opacity: loading ? 0.5 : 1 }}>
          {loading ? "..." : "Generate"}
        </button>
      </div>
    </div>
  );
}

export default function DeckBuilder() {
  const [slides, setSlides] = useState<Slide[]>([BLANK_SLIDE()]);
  const [active, setActive] = useState(0);
  const [title, setTitle] = useState("Untitled Deck");
  const [presenting, setPresenting] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);

  const updateSlide = useCallback((idx: number, html: string) => {
    setSlides(s => s.map((sl, i) => i === idx ? { ...sl, html } : sl));
  }, []);

  const addSlide = () => { setSlides(s => [...s, BLANK_SLIDE()]); setActive(slides.length); };
  const removeSlide = (idx: number) => { if (slides.length <= 1) return; setSlides(s => s.filter((_, i) => i !== idx)); setActive(Math.max(0, idx - 1)); };
  const moveSlide = (from: number, dir: number) => {
    const to = from + dir;
    if (to < 0 || to >= slides.length) return;
    setSlides(s => { const n = [...s]; [n[from], n[to]] = [n[to], n[from]]; return n; });
    setActive(to);
  };

  const exportHTML = () => {
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title><style>
*{margin:0;padding:0;box-sizing:border-box}html,body{height:100%;overflow:hidden;font-family:system-ui,sans-serif;background:#0a0914;color:#f3f0fb}
.deck{height:100vh;overflow-y:scroll;scroll-snap-type:y mandatory}.slide{height:100vh;scroll-snap-align:start;display:flex;align-items:center;justify-content:center;padding:4rem;flex-direction:column}
.slide h1{font-size:3rem;margin-bottom:1rem;font-family:Georgia,serif}.slide h2{font-size:2rem;margin-bottom:0.75rem}.slide p{font-size:1.25rem;opacity:0.8;max-width:60ch;line-height:1.6}
.slide ul,.slide ol{font-size:1.1rem;text-align:left;line-height:2}</style></head><body><div class="deck">
${slides.map(s => `<div class="slide">${s.html}</div>`).join("\n")}</div></body></html>`;
    const blob = new Blob([html], { type: "text/html" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${title.replace(/\s+/g, "-")}.html`; a.click();
  };

  const exportPDF = () => { window.print(); };

  // Presentation mode
  if (presenting) {
    return (
      <div style={{ position: "fixed", inset: 0, background: C.bg, zIndex: 9999, overflow: "hidden" }}>
        <div style={{ height: "100vh", overflowY: "scroll", scrollSnapType: "y mandatory" }}>
          {slides.map((s) => (
            <div key={s.id} style={{ height: "100vh", scrollSnapAlign: "start", display: "flex", alignItems: "center", justifyContent: "center", padding: "4rem", flexDirection: "column" }}
              dangerouslySetInnerHTML={{ __html: s.html }} />
          ))}
        </div>
        <button onClick={() => setPresenting(false)} style={{ position: "fixed", top: 12, right: 12, background: "rgba(0,0,0,0.6)", border: "none", color: C.ink, padding: "6px 12px", borderRadius: 6, cursor: "pointer", fontSize: "0.7rem" }}>Exit (Esc)</button>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.ink, fontFamily: "'Inter Variable', 'Inter', -apple-system, system-ui, sans-serif", padding: "1.5rem 2rem" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <input value={title} onChange={e => setTitle(e.target.value)} style={{ background: "transparent", border: "none", color: C.ink, fontSize: "1.2rem", fontWeight: 700, fontFamily: "Georgia, serif", outline: "none", width: 300 }} />
          <span style={{ fontSize: "0.6rem", color: C.muted }}>{slides.length} slides</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => setPresenting(true)} style={{ padding: "5px 12px", borderRadius: 6, border: "none", background: C.acc, color: "#fff", fontSize: "0.68rem", fontWeight: 600, cursor: "pointer" }}>Present</button>
          <button onClick={exportHTML} style={{ padding: "5px 12px", borderRadius: 6, border: `1px solid ${C.border}`, background: "transparent", color: C.ink, fontSize: "0.68rem", cursor: "pointer" }}>Export HTML</button>
          <button onClick={exportPDF} style={{ padding: "5px 12px", borderRadius: 6, border: `1px solid ${C.border}`, background: "transparent", color: C.ink, fontSize: "0.68rem", cursor: "pointer" }}>Print/PDF</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: "1rem" }}>
        {/* Slide list */}
        <div style={{ width: 140, flexShrink: 0 }}>
          {slides.map((s, i) => (
            <div key={s.id} onClick={() => setActive(i)} style={{ padding: "8px 10px", borderRadius: 8, marginBottom: 4, cursor: "pointer", border: `1px solid ${i === active ? C.acc : C.border}`, background: i === active ? "rgba(167,139,250,0.08)" : C.card, fontSize: "0.65rem", color: i === active ? C.ink : C.muted }}>
              Slide {i + 1}
            </div>
          ))}
          <button onClick={addSlide} style={{ width: "100%", padding: "6px", borderRadius: 6, border: `1px dashed ${C.border}`, background: "transparent", color: C.muted, fontSize: "0.65rem", cursor: "pointer", marginTop: 4 }}>+ Add Slide</button>
        </div>

        {/* Editor */}
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
            <button onClick={() => moveSlide(active, -1)} disabled={active === 0} style={{ background: "none", border: "none", color: active === 0 ? C.dim : C.muted, cursor: "pointer", fontSize: "0.7rem" }}>◀ Move</button>
            <button onClick={() => moveSlide(active, 1)} disabled={active === slides.length - 1} style={{ background: "none", border: "none", color: active === slides.length - 1 ? C.dim : C.muted, cursor: "pointer", fontSize: "0.7rem" }}>Move ▶</button>
            <button onClick={() => removeSlide(active)} disabled={slides.length <= 1} style={{ background: "none", border: "none", color: slides.length <= 1 ? C.dim : C.danger ?? "#e87c7c", cursor: "pointer", fontSize: "0.7rem", marginLeft: "auto" }}>Delete</button>
          </div>
          {/* Editable slide preview */}
          <div ref={previewRef} contentEditable suppressContentEditableWarning
            onBlur={e => updateSlide(active, e.currentTarget.innerHTML)}
            dangerouslySetInnerHTML={{ __html: slides[active]?.html || "" }}
            style={{ aspectRatio: "16/9", background: "#0a0914", border: `1px solid ${C.border}`, borderRadius: 12, padding: 0, overflow: "hidden", outline: "none", fontSize: "0.7rem" }} />
          {/* Speaker notes */}
          <textarea value={slides[active]?.notes || ""} onChange={e => setSlides(s => s.map((sl, i) => i === active ? { ...sl, notes: e.target.value } : sl))}
            placeholder="Speaker notes..."
            style={{ width: "100%", marginTop: 8, minHeight: 60, background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 12px", color: C.muted, fontSize: "0.72rem", resize: "vertical", outline: "none", fontFamily: "inherit" }} />

          {/* Templates */}
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: "0.6rem", color: C.muted, marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>Templates</div>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {TEMPLATES.map(t => (
                <button key={t.name} onClick={() => { setSlides(s => [...s, { id: uid(), html: t.html, notes: "" }]); setActive(slides.length); }}
                  style={{ padding: "4px 10px", borderRadius: 6, border: `1px solid ${C.border}`, background: "transparent", color: C.muted, fontSize: "0.6rem", cursor: "pointer" }}>
                  {t.name}
                </button>
              ))}
            </div>
          </div>

          {/* AI Assistant */}
          <DeckChat slides={slides} onUpdateSlides={setSlides} activeIdx={active} />
        </div>
      </div>
    </div>
  );
}
