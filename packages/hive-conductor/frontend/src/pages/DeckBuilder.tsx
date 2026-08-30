import {
  type ClipboardEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { escapeDeckText, sanitizeDeckMarkup } from "../lib/deckSanitizer";
import { DECK_TEMPLATES } from "../lib/deckTemplates";

const C = { bg: "#0a0914", card: "#11101e", border: "rgba(196,166,97,0.14)", gold: "#c4a661", ink: "#f3f0fb", muted: "#8b83a8", dim: "#5a5478", acc: "#a78bfa", danger: "#e87c7c" };

interface Slide { id: string; html: string; notes: string; }

function uid() { return Math.random().toString(36).slice(2, 10); }

function safeSlide(slide: Slide): Slide {
  return { ...slide, html: sanitizeDeckMarkup(slide.html) };
}

const BLANK_SLIDE: () => Slide = () => ({ id: uid(), html: "<h1>Title</h1><p>Content</p>", notes: "" });

function insertFragmentAtSelection(target: HTMLElement, fragment: DocumentFragment): void {
  const selection = window.getSelection();
  const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
  const lastInserted = fragment.lastChild;

  if (range && target.contains(range.commonAncestorContainer)) {
    range.deleteContents();
    range.insertNode(fragment);
    if (selection && lastInserted) {
      range.setStartAfter(lastInserted);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    return;
  }

  target.appendChild(fragment);
}

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

      const slideMatches = [...reply.matchAll(/<slide(?:\s+index="(\d+)")?>([\s\S]*?)<\/slide>/gi)];
      if (slideMatches.length > 0) {
        const newSlides = [...slides];
        for (const match of slideMatches) {
          const idx = match[1] ? parseInt(match[1]) - 1 : -1;
          const html = sanitizeDeckMarkup(match[2].trim());
          if (idx >= 0 && idx < newSlides.length) {
            newSlides[idx] = { ...newSlides[idx], html };
          } else {
            newSlides.push({ id: uid(), html, notes: "" });
          }
        }
        onUpdateSlides(newSlides.map(safeSlide));
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

  const replaceSlides = useCallback((nextSlides: Slide[]) => {
    setSlides(nextSlides.map(safeSlide));
  }, []);

  const updateSlide = useCallback((idx: number, html: string) => {
    setSlides(s => s.map((sl, i) => i === idx ? { ...sl, html: sanitizeDeckMarkup(html) } : sl));
  }, []);

  const insertPreviewContent = useCallback((target: HTMLDivElement, raw: string, asHtml: boolean) => {
    const fragment = document.createDocumentFragment();
    if (asHtml) {
      const template = document.createElement("template");
      template.innerHTML = sanitizeDeckMarkup(raw);
      fragment.appendChild(template.content);
    } else {
      fragment.appendChild(document.createTextNode(raw));
    }
    insertFragmentAtSelection(target, fragment);
    updateSlide(active, target.innerHTML);
  }, [active, updateSlide]);

  const handlePreviewPaste = useCallback((event: ClipboardEvent<HTMLDivElement>) => {
    // Prevent browser insertion before examining rich clipboard data. An <img>
    // can start a request as soon as it enters the DOM; sanitizing on blur is
    // therefore too late for the trust boundary.
    event.preventDefault();
    if (event.clipboardData.files.length > 0) return;
    const html = event.clipboardData.getData("text/html");
    if (html) {
      insertPreviewContent(event.currentTarget, html, true);
      return;
    }
    insertPreviewContent(event.currentTarget, event.clipboardData.getData("text/plain"), false);
  }, [insertPreviewContent]);

  const handlePreviewDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    // The default drop action can insert rich HTML, load a URI, or navigate.
    // Own the action completely and publish only sanitized markup/plain text.
    event.preventDefault();
    if (event.dataTransfer.files.length > 0) return;
    const html = event.dataTransfer.getData("text/html");
    if (html) {
      insertPreviewContent(event.currentTarget, html, true);
      return;
    }
    const text = event.dataTransfer.getData("text/plain");
    if (text) insertPreviewContent(event.currentTarget, text, false);
  }, [insertPreviewContent]);

  const addSlide = () => { setSlides(s => [...s, BLANK_SLIDE()]); setActive(slides.length); };
  const removeSlide = (idx: number) => { if (slides.length <= 1) return; setSlides(s => s.filter((_, i) => i !== idx)); setActive(Math.max(0, idx - 1)); };
  const moveSlide = (from: number, dir: number) => {
    const to = from + dir;
    if (to < 0 || to >= slides.length) return;
    setSlides(s => { const n = [...s]; [n[from], n[to]] = [n[to], n[from]]; return n; });
    setActive(to);
  };

  const exportHTML = () => {
    const safeTitle = escapeDeckText(title);
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${safeTitle}</title><style>
*{margin:0;padding:0;box-sizing:border-box}html,body{height:100%;overflow:hidden;font-family:system-ui,sans-serif;background:#0a0914;color:#f3f0fb}
.deck{height:100vh;overflow-y:scroll;scroll-snap-type:y mandatory}.slide{height:100vh;scroll-snap-align:start;display:flex;align-items:center;justify-content:center;padding:4rem;flex-direction:column}
.slide h1{font-size:3rem;margin-bottom:1rem;font-family:Georgia,serif}.slide h2{font-size:2rem;margin-bottom:0.75rem}.slide p{font-size:1.25rem;opacity:0.8;max-width:60ch;line-height:1.6}
.slide ul,.slide ol{font-size:1.1rem;text-align:left;line-height:2}</style></head><body><div class="deck">
${slides.map(s => `<div class="slide">${sanitizeDeckMarkup(s.html)}</div>`).join("\n")}</div></body></html>`;
    const blob = new Blob([html], { type: "text/html" });
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = `${title.replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "") || "deck"}.html`;
    a.click();
    URL.revokeObjectURL(objectUrl);
  };

  const exportPDF = () => { window.print(); };

  if (presenting) {
    return (
      <div style={{ position: "fixed", inset: 0, background: C.bg, zIndex: 9999, overflow: "hidden" }}>
        <div style={{ height: "100vh", overflowY: "scroll", scrollSnapType: "y mandatory" }}>
          {slides.map((s) => (
            <div key={s.id} style={{ height: "100vh", scrollSnapAlign: "start", display: "flex", alignItems: "center", justifyContent: "center", padding: "4rem", flexDirection: "column" }}
              dangerouslySetInnerHTML={{ __html: sanitizeDeckMarkup(s.html) }} />
          ))}
        </div>
        <button onClick={() => setPresenting(false)} style={{ position: "fixed", top: 12, right: 12, background: "rgba(0,0,0,0.6)", border: "none", color: C.ink, padding: "6px 12px", borderRadius: 6, cursor: "pointer", fontSize: "0.7rem" }}>Exit (Esc)</button>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.ink, fontFamily: "'Inter Variable', 'Inter', -apple-system, system-ui, sans-serif", padding: "1.5rem 2rem" }}>
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
        <div style={{ width: 140, flexShrink: 0 }}>
          {slides.map((s, i) => (
            <div key={s.id} onClick={() => setActive(i)} style={{ padding: "8px 10px", borderRadius: 8, marginBottom: 4, cursor: "pointer", border: `1px solid ${i === active ? C.acc : C.border}`, background: i === active ? "rgba(167,139,250,0.08)" : C.card, fontSize: "0.65rem", color: i === active ? C.ink : C.muted }}>
              Slide {i + 1}
            </div>
          ))}
          <button onClick={addSlide} style={{ width: "100%", padding: "6px", borderRadius: 6, border: `1px dashed ${C.border}`, background: "transparent", color: C.muted, fontSize: "0.65rem", cursor: "pointer", marginTop: 4 }}>+ Add Slide</button>
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
            <button onClick={() => moveSlide(active, -1)} disabled={active === 0} style={{ background: "none", border: "none", color: active === 0 ? C.dim : C.muted, cursor: "pointer", fontSize: "0.7rem" }}>◀ Move</button>
            <button onClick={() => moveSlide(active, 1)} disabled={active === slides.length - 1} style={{ background: "none", border: "none", color: active === slides.length - 1 ? C.dim : C.muted, cursor: "pointer", fontSize: "0.7rem" }}>Move ▶</button>
            <button onClick={() => removeSlide(active)} disabled={slides.length <= 1} style={{ background: "none", border: "none", color: slides.length <= 1 ? C.dim : C.danger, cursor: "pointer", fontSize: "0.7rem", marginLeft: "auto" }}>Delete</button>
          </div>
          <div ref={previewRef} contentEditable suppressContentEditableWarning
            onPaste={handlePreviewPaste}
            onDrop={handlePreviewDrop}
            onBlur={e => updateSlide(active, e.currentTarget.innerHTML)}
            dangerouslySetInnerHTML={{ __html: sanitizeDeckMarkup(slides[active]?.html || "") }}
            style={{ aspectRatio: "16/9", background: "#0a0914", border: `1px solid ${C.border}`, borderRadius: 12, padding: 0, overflow: "hidden", outline: "none", fontSize: "0.7rem" }} />
          <textarea value={slides[active]?.notes || ""} onChange={e => setSlides(s => s.map((sl, i) => i === active ? { ...sl, notes: e.target.value } : sl))}
            placeholder="Speaker notes..."
            style={{ width: "100%", marginTop: 8, minHeight: 60, background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 12px", color: C.muted, fontSize: "0.72rem", resize: "vertical", outline: "none", fontFamily: "inherit" }} />

          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: "0.6rem", color: C.muted, marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>Templates</div>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {DECK_TEMPLATES.map(t => (
                <button key={t.name} onClick={() => { setSlides(s => [...s, safeSlide({ id: uid(), html: t.html, notes: "" })]); setActive(slides.length); }}
                  style={{ padding: "4px 10px", borderRadius: 6, border: `1px solid ${C.border}`, background: "transparent", color: C.muted, fontSize: "0.6rem", cursor: "pointer" }}>
                  {t.name}
                </button>
              ))}
            </div>
          </div>

          <DeckChat slides={slides} onUpdateSlides={replaceSlides} activeIdx={active} />
        </div>
      </div>
    </div>
  );
}
