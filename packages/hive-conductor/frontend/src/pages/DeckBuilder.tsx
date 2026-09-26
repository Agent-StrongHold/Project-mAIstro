import {
  type ClipboardEvent,
  type DragEvent,
  type FocusEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { escapeDeckText, sanitizeDeckMarkup } from "../lib/deckSanitizer";
import { DECK_TEMPLATES } from "../lib/deckTemplates";
import { randomId } from "../lib/ids";

const C = { bg: "#0a0914", card: "#11101e", border: "rgba(196,166,97,0.14)", gold: "#c4a661", ink: "#f3f0fb", muted: "#b5adc9", dim: "#80789d", acc: "#a78bfa", danger: "#e87c7c" };
interface Slide { id: string; html: string; notes: string; }
type DeckBuilderProps = { initialPrompt?: string; onExit?: () => void; onSave?: () => Promise<void> };

function uid() { return randomId(); }

function safeSlide(slide: Slide): Slide { return { ...slide, html: sanitizeDeckMarkup(slide.html) }; }
const BLANK_SLIDE = (prompt = ""): Slide => ({ id: uid(), html: `<h1>${escapeDeckText(prompt || "Title")}</h1><p>Content</p>`, notes: "" });

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
  const [status, setStatus] = useState("Describe a change to the selected slide.");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [msgs]);

  const submit = async () => {
    if (!value.trim() || loading) return;
    const userMsg = value.trim();
    setValue("");
    setMsgs((current) => [...current, { role: "user", content: userMsg }]);
    setLoading(true);
    setStatus("Generating a response...");
    try {
      const r = await fetch("/v1/chat/complete", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: [{ role: "user", content: `[DECK CONTEXT: ${slides.length} slides, active=#${activeIdx + 1}]\n\n${userMsg}` }] }) });
      const data = await r.json();
      const reply = data?.choices?.[0]?.message?.content || data?.content || "No response";
      setMsgs((current) => [...current, { role: "assistant", content: reply }]);
      const slideMatches = [...reply.matchAll(/<slide(?:\s+index="(\d+)")?>([\s\S]*?)<\/slide>/gi)];
      if (slideMatches.length > 0) {
        const next = [...slides];
        for (const match of slideMatches) {
          const index = match[1] ? Number.parseInt(match[1], 10) - 1 : -1;
          const html = sanitizeDeckMarkup(match[2].trim());
          if (index >= 0 && index < next.length) next[index] = { ...next[index], html };
          else next.push({ id: uid(), html, notes: "" });
        }
        onUpdateSlides(next.map(safeSlide));
        setStatus("Slide changes applied safely.");
      } else setStatus("Response received; no slide markup was applied.");
    } catch { setMsgs((current) => [...current, { role: "assistant", content: "Connection error - check that the backend is running." }]); setStatus("Generation failed; the draft is unchanged."); }
    setLoading(false);
  };

  return <section aria-labelledby="deck-chat-title" style={{ borderTop: `1px solid ${C.border}`, marginTop: "1rem", paddingTop: "0.75rem" }}>
    <h2 id="deck-chat-title" style={{ fontSize: "var(--text-floor)", color: C.muted, margin: "0 0 6px", textTransform: "uppercase" }}>Slide assistant</h2>
    {msgs.length > 0 && <div ref={ref} aria-label="Assistant messages" style={{ maxHeight: 150, overflowY: "auto", marginBottom: 8, display: "flex", flexDirection: "column", gap: 4 }}>{msgs.slice(-6).map((message, index) => <div key={index} style={{ fontSize: "var(--text-floor)", color: message.role === "user" ? C.gold : C.muted, lineHeight: 1.4 }}><span style={{ fontWeight: 600 }}>{message.role === "user" ? "You" : "Assistant"}: </span>{message.content.replace(/<slide[^>]*>[\s\S]*?<\/slide>/gi, "[slide generated]").slice(0, 200)}</div>)}</div>}
    <div role="status" aria-live="polite" style={{ color: C.muted, fontSize: "var(--text-floor)", marginBottom: 6 }}>{status}</div>
    <div style={{ display: "flex", gap: 6 }}><label htmlFor="deck-assistant-input" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden" }}>Describe slide changes</label><input id="deck-assistant-input" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void submit(); }} placeholder="Describe slides to generate, or ask to edit..." style={{ flex: 1, background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 12px", color: C.ink, fontSize: "var(--text-floor)" }} /><button type="button" onClick={() => void submit()} disabled={loading}>{loading ? "Generating..." : "Generate"}</button></div>
  </section>;
}

export default function DeckBuilder({ initialPrompt = "", onExit, onSave }: DeckBuilderProps) {
  const [slides, setSlides] = useState<Slide[]>([BLANK_SLIDE(initialPrompt)]);
  const [active, setActive] = useState(0);
  const [title, setTitle] = useState("Untitled Deck");
  const [presenting, setPresenting] = useState(false);
  const [presentationSlide, setPresentationSlide] = useState(0);
  const [status, setStatus] = useState("Deck editor ready. Select a slide or use the ordered-page controls.");
  const [saving, setSaving] = useState(false);
  // WCAG 2.4.7 focus visibility for the editable slide canvas: inline styles
  // cannot express :focus-visible, so focus is tracked in state and the
  // resting outline (none) is swapped for a 2px accent outline while focused.
  const [editorFocused, setEditorFocused] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const presentationExitRef = useRef<HTMLButtonElement>(null);
  // Dialog container for the aria-modal presentation surface. Tab is trapped
  // inside it while presenting (see the keydown handler below), so a handle
  // on the container is needed to enumerate its focusable controls.
  const presentationRef = useRef<HTMLDivElement>(null);
  // Deterministic entry focus: Design Studio swaps this editor in for the page
  // behind it (and /decks mounts it at its route), so the control that opened
  // the editor is unmounted and focus would otherwise fall to <body>. Focusing
  // the visible Deck title input gives the editor a real first tab stop that
  // keyboard users can see and announce (WCAG 2.4.3 / 2.4.7).
  const deckTitleRef = useRef<HTMLInputElement>(null);
  // Live handle on the Present button. The editor unmounts while presenting,
  // so a stored element from entry time would be detached by exit time and
  // focus restoration would silently no-op; the ref re-resolves after the
  // editor remounts.
  const presentButtonRef = useRef<HTMLButtonElement>(null);
  // True only when presentation was actually entered, so the restore effect
  // never steals focus on the editor's first mount.
  const restorePresentationFocusRef = useRef(false);

  useEffect(() => {
    deckTitleRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!presenting) return;
    presentationExitRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setPresenting(false); return; }
      if (event.key === "Tab") {
        const container = presentationRef.current;
        if (!container) return;
        // aria-modal="true" tells assistive tech nothing outside the dialog
        // exists; the keyboard must honor that promise too. Cycle Tab and
        // Shift+Tab among the dialog's focusable controls (disabled ones are
        // skipped, matching the browser's own Tab behavior) so focus can never
        // escape into the app shell behind the full-screen overlay.
        event.preventDefault();
        const focusable = Array.from(container.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex='-1'])"));
        if (focusable.length === 0) return;
        const current = focusable.indexOf(document.activeElement as HTMLElement);
        const next = event.shiftKey
          ? (current <= 0 ? focusable.length - 1 : current - 1)
          : (current === focusable.length - 1 ? 0 : current + 1);
        focusable[next].focus();
        return;
      }
      if (event.key === "ArrowRight" || event.key === "PageDown") { event.preventDefault(); setPresentationSlide((current) => Math.min(slides.length - 1, current + 1)); }
      if (event.key === "ArrowLeft" || event.key === "PageUp") { event.preventDefault(); setPresentationSlide((current) => Math.max(0, current - 1)); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [presenting, slides.length]);

  useEffect(() => {
    if (!presenting && restorePresentationFocusRef.current) {
      restorePresentationFocusRef.current = false;
      presentButtonRef.current?.focus();
    }
  }, [presenting]);

  const replaceSlides = useCallback((nextSlides: Slide[]) => setSlides(nextSlides.map(safeSlide)), []);
  const updateSlide = useCallback((index: number, html: string) => setSlides((current) => current.map((slide, i) => i === index ? { ...slide, html: sanitizeDeckMarkup(html) } : slide)), []);
  const insertPreviewContent = useCallback((target: HTMLDivElement, raw: string, asHtml: boolean) => {
    const fragment = document.createDocumentFragment();
    if (asHtml) { const template = document.createElement("template"); template.innerHTML = sanitizeDeckMarkup(raw); fragment.appendChild(template.content); } else fragment.appendChild(document.createTextNode(raw));
    insertFragmentAtSelection(target, fragment);
    updateSlide(active, target.innerHTML);
    setStatus("Edited slide content updated safely.");
  }, [active, updateSlide]);
  const handlePreviewPaste = useCallback((event: ClipboardEvent<HTMLDivElement>) => { event.preventDefault(); if (event.clipboardData.files.length > 0) return; const html = event.clipboardData.getData("text/html"); insertPreviewContent(event.currentTarget, html || event.clipboardData.getData("text/plain"), Boolean(html)); }, [insertPreviewContent]);
  const handlePreviewDrop = useCallback((event: DragEvent<HTMLDivElement>) => { event.preventDefault(); if (event.dataTransfer.files.length > 0) return; const html = event.dataTransfer.getData("text/html"); const text = event.dataTransfer.getData("text/plain"); if (html || text) insertPreviewContent(event.currentTarget, html || text, Boolean(html)); }, [insertPreviewContent]);
  const handlePreviewBlur = useCallback((event: FocusEvent<HTMLDivElement>) => {
    const safeHtml = sanitizeDeckMarkup(event.currentTarget.innerHTML);
    // Do not leave an edited DOM value live in the browser between blur and
    // React's state commit. The same boundary protects both the DOM and state.
    event.currentTarget.innerHTML = safeHtml;
    updateSlide(active, safeHtml);
  }, [active, updateSlide]);

  function selectSlide(index: number): void { setActive(index); setStatus(`Slide ${index + 1} selected.`); }
  function addSlide(template?: string): void { const slide = safeSlide({ id: uid(), html: template ?? "<h1>Title</h1><p>Content</p>", notes: "" }); setSlides((current) => [...current, slide]); setActive(slides.length); setStatus(`Slide ${slides.length + 1} added and selected.`); }
  function removeSlide(index: number): void { if (slides.length <= 1) return; setSlides((current) => current.filter((_, i) => i !== index)); const next = Math.max(0, index - 1); setActive(next); setStatus(`Slide ${index + 1} deleted.`); }
  function moveSlide(from: number, direction: -1 | 1): void { const to = from + direction; if (to < 0 || to >= slides.length) return; setSlides((current) => { const next = [...current]; [next[from], next[to]] = [next[to], next[from]]; return next; }); setActive(to); setStatus(`Slide moved to position ${to + 1}.`); }
  function startPresentation(): void { restorePresentationFocusRef.current = true; setPresentationSlide(active); setPresenting(true); }
  async function saveDeck(): Promise<void> { if (!onSave || saving) return; setSaving(true); setStatus("Saving project through the Design service..."); try { await onSave(); setStatus("Project saved. This editor remains available for local changes."); } catch (error) { setStatus(error instanceof Error ? `Project save failed: ${error.message}` : "Project save failed."); } finally { setSaving(false); } }
  function exportHTML(): void { const safeTitle = escapeDeckText(title); const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${safeTitle}</title></head><body><main>${slides.map((slide) => `<section>${sanitizeDeckMarkup(slide.html)}</section>`).join("\n")}</main></body></html>`; const url = URL.createObjectURL(new Blob([html], { type: "text/html" })); const link = document.createElement("a"); link.href = url; link.download = `${title.replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "") || "deck"}.html`; link.click(); URL.revokeObjectURL(url); setStatus("Deck exported as HTML."); }

  if (presenting) return <div ref={presentationRef} role="dialog" aria-modal="true" aria-labelledby="presentation-title" style={{ position: "fixed", inset: 0, background: C.bg, zIndex: 9999, color: C.ink, overflow: "hidden", padding: 16 }}><h1 id="presentation-title" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden" }}>{title} presentation</h1><div style={{ height: "calc(100vh - 70px)", display: "flex", alignItems: "center", justifyContent: "center" }}><div style={{ width: "min(100%, 1000px)", maxHeight: "100%", aspectRatio: "16/9", overflow: "auto", padding: "4rem", boxSizing: "border-box" }} dangerouslySetInnerHTML={{ __html: sanitizeDeckMarkup(slides[presentationSlide]?.html || "") }} /></div><div style={{ position: "fixed", bottom: 12, left: 12, right: 12, display: "flex", justifyContent: "center", gap: 8, alignItems: "center" }}><button type="button" onClick={() => setPresentationSlide((current) => Math.max(0, current - 1))} disabled={presentationSlide === 0}>Previous slide</button><span aria-live="polite">Slide {presentationSlide + 1} of {slides.length}</span><button type="button" onClick={() => setPresentationSlide((current) => Math.min(slides.length - 1, current + 1))} disabled={presentationSlide === slides.length - 1}>Next slide</button></div><button ref={presentationExitRef} type="button" onClick={() => setPresenting(false)} style={{ position: "fixed", top: 12, right: 12 }}>{"Exit (Esc)"}</button></div>;

  return <div aria-labelledby="deck-editor-title" style={{ minHeight: "100vh", background: C.bg, color: C.ink, fontFamily: "var(--sans)", padding: "1.5rem 2rem" }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", gap: 12, flexWrap: "wrap" }}><div style={{ display: "flex", alignItems: "center", gap: 12 }}><label htmlFor="deck-title" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden" }}>Deck title</label><input id="deck-title" ref={deckTitleRef} value={title} onChange={(event) => setTitle(event.target.value)} style={{ background: "transparent", border: "none", color: C.ink, fontSize: "1.2rem", fontWeight: 700, width: 300 }} /><span style={{ fontSize: "0.6rem", color: C.muted }}>{slides.length} slides</span></div><div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{onExit && <button type="button" onClick={onExit}>Back to Design Studio</button>}{onSave && <button type="button" onClick={() => void saveDeck()} disabled={saving}>{saving ? "Saving..." : "Save project"}</button>}<button ref={presentButtonRef} type="button" onClick={startPresentation}>Present</button><button type="button" onClick={exportHTML}>Export HTML</button><button type="button" onClick={() => { window.print(); setStatus("Print dialog opened."); }}>Print/PDF</button></div></div>
    <h1 id="deck-editor-title" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden" }}>Deck editor</h1><p role="status" aria-live="polite" style={{ minHeight: 18, color: C.muted, fontSize: "0.7rem" }}>{status}</p>
    <div style={{ display: "grid", gridTemplateColumns: "140px minmax(0, 1fr)", gap: "1rem" }}><aside aria-labelledby="deck-pages-title"><h2 id="deck-pages-title" style={{ fontSize: "0.7rem", color: C.muted }}>Pages</h2><div role="listbox" aria-label="Ordered deck pages" aria-describedby="deck-pages-help" style={{ display: "grid", gap: 4 }}>{slides.map((slide, index) => <button key={slide.id} type="button" role="option" aria-selected={index === active} aria-label={`Slide ${index + 1}`} onClick={() => selectSlide(index)} style={{ textAlign: "left", borderColor: index === active ? C.acc : C.border, background: index === active ? "rgba(167,139,250,0.14)" : C.card, color: index === active ? C.ink : C.muted }}>Slide {index + 1}</button>)}</div><p id="deck-pages-help" style={{ fontSize: "0.62rem", color: C.muted, lineHeight: 1.4 }}>Tab to a page and press Enter. Reorder with Move earlier/later; no drag operation is required.</p><button type="button" onClick={() => addSlide()}>+ Add slide</button></aside>
      <section aria-labelledby="active-slide-title"><h2 id="active-slide-title" style={{ fontSize: "0.7rem", color: C.muted }}>Slide {active + 1} editor</h2><div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap" }}><button type="button" onClick={() => moveSlide(active, -1)} disabled={active === 0}>Move earlier</button><button type="button" onClick={() => moveSlide(active, 1)} disabled={active === slides.length - 1}>Move later</button><button type="button" onClick={() => removeSlide(active)} disabled={slides.length <= 1}>Delete slide</button></div><div ref={previewRef} role="textbox" aria-multiline="true" aria-label={`Edit slide ${active + 1} content`} aria-describedby="slide-edit-help" contentEditable suppressContentEditableWarning onPaste={handlePreviewPaste} onDragOver={(event) => event.preventDefault()} onDrop={handlePreviewDrop} onFocus={() => setEditorFocused(true)} onBlur={(event) => { setEditorFocused(false); handlePreviewBlur(event); }} dangerouslySetInnerHTML={{ __html: sanitizeDeckMarkup(slides[active]?.html || "") }} style={{ aspectRatio: "16/9", background: C.bg, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24, overflow: "auto", outline: editorFocused ? `2px solid ${C.acc}` : "none", outlineOffset: 2, fontSize: "0.9rem" }} /><p id="slide-edit-help" style={{ color: C.muted, fontSize: "0.65rem" }}>Editable slide content. Paste and drop are sanitized before insertion. Use Tab to reach controls and do not rely on dragging.</p><label htmlFor="speaker-notes" style={{ fontSize: "0.7rem", color: C.muted }}>Speaker notes</label><textarea id="speaker-notes" value={slides[active]?.notes || ""} onChange={(event) => setSlides((current) => current.map((slide, index) => index === active ? { ...slide, notes: event.target.value } : slide))} placeholder="Speaker notes..." style={{ width: "100%", marginTop: 8, minHeight: 60, boxSizing: "border-box", background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 12px", color: C.muted, fontSize: "0.72rem", resize: "vertical" }} /><section aria-labelledby="deck-templates-title" style={{ marginTop: 12 }}><h2 id="deck-templates-title" style={{ fontSize: "0.6rem", color: C.muted, textTransform: "uppercase" }}>Templates</h2><div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{DECK_TEMPLATES.map((template) => <button type="button" key={template.name} onClick={() => addSlide(template.html)}>{template.name}</button>)}</div></section><DeckChat slides={slides} onUpdateSlides={replaceSlides} activeIdx={active} /></section></div>
  </div>;

}
