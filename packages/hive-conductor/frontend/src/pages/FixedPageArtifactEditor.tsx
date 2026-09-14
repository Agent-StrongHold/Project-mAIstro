import { useCallback, useState, type ClipboardEvent, type DragEvent } from "react";
import {
  createSanitizedVisualArtifactFragment,
  escapeVisualArtifactText,
  recommendVisualArtifactTrust,
  SanitizedVisualArtifact,
  sanitizeVisualArtifactMarkup,
} from "../lib/visualArtifactRenderer";

export type FixedPageMode =
  | "poster"
  | "infographic"
  | "flyer"
  | "social"
  | "card"
  | "cover"
  | "diagram"
  | "custom";

const MODE_LABELS: Record<FixedPageMode, string> = {
  poster: "Poster",
  infographic: "Infographic",
  flyer: "Flyer",
  social: "Social graphic",
  card: "Card",
  cover: "Cover",
  diagram: "Diagram / visual",
  custom: "Custom canvas",
};

const DEFAULT_MARKUP: Record<FixedPageMode, string> = {
  poster: '<article style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:360px;padding:32px;background:linear-gradient(135deg,#14213d,#1f6f8b);color:#fff;text-align:center"><p style="font-size:12px;letter-spacing:2px;text-transform:uppercase">Design Studio</p><h1 style="font-size:42px;margin:12px 0">Make it memorable.</h1><p style="max-width:36ch">A safe fixed-page visual template ready for your content.</p></article>',
  infographic: '<article style="display:flex;gap:24px;align-items:center;min-height:360px;padding:32px;background:#f5f1e8;color:#17202a"><div style="flex:1"><p style="font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#b15b3e">At a glance</p><h1 style="font-size:34px">One clear idea</h1><p>Combine measured text, typography, and vector shapes without active browser content.</p></div><svg width="180" height="180" viewBox="0 0 180 180" role="img" aria-label="Example chart"><circle cx="90" cy="90" r="66" fill="none" stroke="#d7c9ad" stroke-width="20"></circle><circle cx="90" cy="90" r="66" fill="none" stroke="#b15b3e" stroke-width="20" stroke-dasharray="280 415" transform="rotate(-90 90 90)"></circle><text x="90" y="98" text-anchor="middle" font-size="28" font-weight="700" fill="#17202a">68%</text></svg></article>',
  flyer: '<article style="padding:32px;min-height:360px;background:#fff8ed;color:#3f2d27"><h1 style="font-size:40px">Something worth sharing</h1><hr style="border:0;border-top:2px solid #d8784a"><p style="font-size:18px;line-height:1.5">A compact message with a strong point of view and room for the details that matter.</p></article>',
  social: '<article style="display:flex;flex-direction:column;justify-content:space-between;min-height:360px;padding:28px;background:#183a37;color:#f1ead8"><p style="font-size:12px;letter-spacing:2px;text-transform:uppercase">Field notes</p><h1 style="font-size:38px;max-width:12ch">Small format. Big signal.</h1><p style="margin:0">@yourstudio</p></article>',
  card: '<article style="display:flex;flex-direction:column;justify-content:center;min-height:360px;padding:36px;background:#efe4d0;color:#332c27;text-align:center"><h1 style="font-size:34px">You are invited</h1><p style="font-size:17px">A considered card for a considered moment.</p></article>',
  cover: '<article style="display:flex;flex-direction:column;justify-content:flex-end;min-height:360px;padding:36px;background:linear-gradient(180deg,#34495e,#101820);color:#fff"><p style="font-size:12px;text-transform:uppercase;letter-spacing:2px">A visual essay</p><h1 style="font-size:42px;margin:10px 0 0">The long view</h1></article>',
  diagram: '<article style="display:flex;align-items:center;justify-content:center;min-height:360px;padding:28px;background:#f7faf9;color:#17202a"><svg width="360" height="150" viewBox="0 0 360 150" role="img" aria-label="Three step process"><rect x="10" y="50" width="90" height="50" rx="8" fill="#cfe8df"></rect><rect x="135" y="50" width="90" height="50" rx="8" fill="#b8d8e8"></rect><rect x="260" y="50" width="90" height="50" rx="8" fill="#f2d4a7"></rect><line x1="100" y1="75" x2="135" y2="75" stroke="#53636b" stroke-width="3"></line><line x1="225" y1="75" x2="260" y2="75" stroke="#53636b" stroke-width="3"></line><text x="55" y="80" text-anchor="middle" font-size="14">Brief</text><text x="180" y="80" text-anchor="middle" font-size="14">Shape</text><text x="305" y="80" text-anchor="middle" font-size="14">Share</text></svg></article>',
  custom: '<article style="display:flex;align-items:center;justify-content:center;min-height:360px;padding:32px;background:#edf0f2;color:#28343b"><h1>Custom fixed canvas</h1></article>',
};

function insertAtSelection(target: HTMLElement, fragment: DocumentFragment): void {
  const selection = window.getSelection();
  const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
  if (range && target.contains(range.commonAncestorContainer)) {
    range.deleteContents();
    range.insertNode(fragment);
    return;
  }
  target.appendChild(fragment);
}

export type FixedPageArtifactEditorProps = {
  mode: FixedPageMode;
  initialMarkup?: string;
  onMarkupChange?: (markup: string) => void;
};

export default function FixedPageArtifactEditor({
  mode,
  initialMarkup,
  onMarkupChange,
}: FixedPageArtifactEditorProps) {
  const sourceMarkup = initialMarkup ?? DEFAULT_MARKUP[mode];
  const [markup, setMarkup] = useState(() => sanitizeVisualArtifactMarkup(sourceMarkup));
  const [trustRecommendation, setTrustRecommendation] = useState(() =>
    recommendVisualArtifactTrust(sourceMarkup),
  );

  const commitMarkup = useCallback(
    (nextMarkup: string) => {
      setTrustRecommendation(recommendVisualArtifactTrust(nextMarkup));
      const safeMarkup = sanitizeVisualArtifactMarkup(nextMarkup);
      setMarkup(safeMarkup);
      onMarkupChange?.(safeMarkup);
    },
    [onMarkupChange],
  );

  const insertContent = useCallback(
    (target: HTMLDivElement, raw: string, asHtml: boolean) => {
      const fragment = asHtml
        ? createSanitizedVisualArtifactFragment(raw)
        : document.createDocumentFragment();
      if (!asHtml) fragment.appendChild(document.createTextNode(raw));
      insertAtSelection(target, fragment);
      commitMarkup(target.innerHTML);
    },
    [commitMarkup],
  );

  const handlePaste = useCallback(
    (event: ClipboardEvent<HTMLDivElement>) => {
      event.preventDefault();
      if (event.clipboardData.files.length > 0) return;
      const html = event.clipboardData.getData("text/html");
      insertContent(event.currentTarget, html || event.clipboardData.getData("text/plain"), Boolean(html));
    },
    [insertContent],
  );

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      if (event.dataTransfer.files.length > 0) return;
      const html = event.dataTransfer.getData("text/html");
      const text = html || event.dataTransfer.getData("text/plain");
      if (text) insertContent(event.currentTarget, text, Boolean(html));
    },
    [insertContent],
  );

  const exportHTML = () => {
    const title = escapeVisualArtifactText(`${MODE_LABELS[mode]} - Design Studio`);
    const safeMarkup = sanitizeVisualArtifactMarkup(markup);
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title><style>html,body{margin:0;min-height:100%;font-family:system-ui,sans-serif}.visual-artifact{max-width:960px;margin:0 auto;min-height:100vh}</style></head><body><div class="visual-artifact">${safeMarkup}</div></body></html>`;
    const blob = new Blob([html], { type: "text/html" });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${mode}-design-studio.html`;
    link.click();
    URL.revokeObjectURL(objectUrl);
  };

  return (
    <section
      aria-label={`${MODE_LABELS[mode]} editor`}
      data-testid="fixed-page-editor"
      data-trust-recommendation={trustRecommendation}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <div>
          <strong>{MODE_LABELS[mode]} preview</strong>
          <div style={{ color: "var(--pencil)", fontSize: 11, marginTop: 3 }}>
            Loaded, edited, and exported content uses the shared visual boundary.
          </div>
        </div>
        <button type="button" className="btn" onClick={exportHTML}>Export HTML</button>
      </div>
      <SanitizedVisualArtifact
        contentEditable
        suppressContentEditableWarning
        aria-label={`${MODE_LABELS[mode]} visual preview`}
        onPaste={handlePaste}
        onDrop={handleDrop}
        onBlur={(event) => commitMarkup(event.currentTarget.innerHTML)}
        markup={markup}
        style={{ minHeight: 360, overflow: "hidden", border: "1px solid var(--rule)", borderRadius: 8, outline: "none" }}
      />
    </section>
  );
}
