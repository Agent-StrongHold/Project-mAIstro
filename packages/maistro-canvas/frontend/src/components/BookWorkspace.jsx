import { useState, useEffect, useRef, useCallback } from "react";
import { decomposeBook } from "../lib/storyApi";
import { generateScenePlan } from "../lib/templateEngine";
import {
  renderStoryboardOverview,
  renderCharacterReferences,
  renderStyleSample,
  renderLayerDraft,
  renderLayerFinal,
  compositeScene,
} from "../lib/renderingPipeline";
import { refineScene } from "../lib/refinementPass";
import { saveState, loadState, clearState } from "../lib/persistence";
import CanvasViewport from "./CanvasViewport";
import { logGenerationAttempt, updateVerdict, saveLayoutVersion } from "../lib/generationTracker";
import { exportBookPdf } from "../lib/exportPdf";

const S = {
  loading: "loading",
  reviewStory: "reviewStory",
  reviewStyle: "reviewStyle",
  reviewCharacter: "reviewCharacter",
  storyboard: "storyboard",
  pages: "pages",
  done: "done",
};

const DEFAULT_TEXT_STYLE = {
  font_family: "Quicksand",
  font_size: 14,
  font_weight: "normal",
  font_style: "normal",
  color: "#333333",
  line_height: 1.4,
  letter_spacing: 0,
  text_align: "center",
};

const DEFAULT_BOX_STYLE = {
  background_color: "rgba(255,255,255,0.85)",
  border_radius: 4,
  padding: { top: 8, right: 12, bottom: 8, left: 12 },
};

const GOOGLE_FONTS = [
  "Quicksand",
  "Nunito",
  "Patrick Hand",
  "Bubblegum Sans",
  "Fredoka One",
  "Baloo 2",
  "Comic Neue",
  "Grandstander",
  "Lilita One",
  "Comfortaa",
];

function buildPageLayers(sp, bookPlan) {
  const dw = bookPlan?.page_dims?.w || 1536;
  const dh = bookPlan?.page_dims?.h || 1024;
  const layers = [];
  layers.push({ id: `${sp.id}-bg`, name: "Background", type: "background", prompt: sp.bg_prompt, image_url: null, quality: "draft", z_index: 0, slot: "full_page", x: 0, y: 0, width: dw, height: dh });
  if (sp.character_prompt) {
    layers.push({ id: `${sp.id}-char`, name: "Character", type: "character", prompt: sp.character_prompt, image_url: null, quality: "draft", z_index: 10, slot: sp.character_slot?.slot_bounds || sp.composition?.character_slot, pose: sp.character_slot?.pose, x: Math.round(dw * 0.55), y: Math.round(dh * 0.1), width: Math.round(dw * 0.4), height: Math.round(dh * 0.8) });
  }
  for (let i = 0; i < (sp.prop_prompts || []).length; i++) {
    const p = sp.prop_prompts[i];
    layers.push({ id: `${sp.id}-prop${i}`, name: p.name, type: "prop", prompt: p.prompt, image_url: null, quality: "draft", z_index: 5 + i, placement: p.placement, x: Math.round(dw * 0.1 + i * dw * 0.2), y: Math.round(dh * 0.6), width: Math.round(dw * 0.15), height: Math.round(dh * 0.15) });
  }
  if (sp.scene_type === "title_page") {
    layers.push({
      id: `${sp.id}-title`, name: "Title Text", type: "text",
      text_content: sp.title || bookPlan?.title || "", subtext: bookPlan?.dedication || "",
      image_url: null, quality: "final", z_index: 20,
      x: Math.round(dw * 0.1), y: Math.round(dh * 0.25),
      width: Math.round(dw * 0.8), height: Math.round(dh * 0.5),
      style: { ...DEFAULT_TEXT_STYLE, font_size: 36, font_weight: "bold", color: "#1a1a2e" },
      box: { ...DEFAULT_BOX_STYLE, background_color: "rgba(255,255,255,0.9)" },
    });
  }
  if (sp.page_text && sp.scene_type !== "title_page") {
    layers.push({
      id: `${sp.id}-text`, name: "Page Text", type: "text",
      text_content: sp.page_text, image_url: null, quality: "final", z_index: 20,
      x: Math.round(dw * 0.05), y: Math.round(dh * 0.75),
      width: Math.round(dw * 0.9), height: Math.round(dh * 0.2),
      style: { ...DEFAULT_TEXT_STYLE },
      box: { ...DEFAULT_BOX_STYLE },
    });
  }
  return layers;
}

function Editable({ value, onChange, multiline, style }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  if (editing) {
    const commit = () => { onChange(draft); setEditing(false); };
    const Tag = multiline ? "textarea" : "input";
    return <Tag autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (!multiline && e.key === "Enter") commit(); if (e.key === "Escape") { setDraft(value); setEditing(false); } }} style={{ width: "100%", fontSize: 12, padding: "2px 6px", minHeight: multiline ? 60 : undefined, ...style }} />;
  }
  return <span onClick={() => { setDraft(value || ""); setEditing(true); }} style={{ cursor: "pointer", ...style }}>{value || <em style={{ color: "var(--text-dim)" }}>click to edit</em>}</span>;
}

function VersionPicker({ versions, selectedIdx, onSelect, label }) {
  if (!versions || versions.length === 0) return null;
  return (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8 }}>
      {versions.map((v, i) => (
        <div key={i} onClick={() => onSelect(i)} style={{
          width: 48, height: 48, borderRadius: 4, overflow: "hidden", cursor: "pointer",
          border: i === selectedIdx ? "2px solid var(--phosphor)" : "2px solid var(--border)",
          opacity: i === selectedIdx ? 1 : 0.6,
        }}>
          <img src={v} alt={`${label} v${i + 1}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      ))}
    </div>
  );
}

export default function BookWorkspace({ bookSpec, onReset }) {
  const [step, setStep] = useState(S.loading);
  const [bookPlan, setBookPlan] = useState(null);
  const [rawDecomp, setRawDecomp] = useState(null);
  const [styleVersions, setStyleVersions] = useState([]);
  const [styleIdx, setStyleIdx] = useState(0);
  const [charSheets, setCharSheets] = useState([]);
  const [sbVersions, setSbVersions] = useState([]);
  const [sbIdx, setSbIdx] = useState(0);
  const [pageLayers, setPageLayers] = useState([]);
  const [currentScene, setCurrentScene] = useState(0);
  const [log, setLog] = useState([]);
  const [selectedLayerId, setSelectedLayerId] = useState(null);
  const [transformingLayer, setTransformingLayer] = useState(null);
  const [transformText, setTransformText] = useState("");
  const [generating, setGenerating] = useState("");
  const [exporting, setExporting] = useState(false);
  const busyRef = useRef(false);
  const saveTimerRef = useRef(null);
  const layoutSaveTimerRef = useRef(null);

  const addLog = useCallback((msg) => setLog((p) => [...p.slice(-100), msg]), []);

  const curStyle = styleVersions[styleIdx] || null;
  const curSb = sbVersions[sbIdx] || null;

  const scheduleSave = useCallback((overrides = {}) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      const title = bookSpec?.title || bookSpec?.premise?.slice(0, 30) || bookSpec?._storageKey;
      if (!title) return;
      saveState(title, { step, bookSpec, rawDecomp, bookPlan, styleVersions, styleIdx, charSheets, sbVersions, sbIdx, pageLayers, currentScene, log: log.slice(-50), savedAt: new Date().toISOString(), ...overrides });
    }, 3000);
  }, [step, bookSpec, rawDecomp, bookPlan, styleVersions, styleIdx, charSheets, sbVersions, sbIdx, pageLayers, currentScene, log]);


  useEffect(() => { scheduleSave(); }, [step, styleVersions, charSheets, sbVersions, pageLayers, currentScene]);

  useEffect(() => {
    (async () => {
      const title = bookSpec?._storageKey || bookSpec?.title || bookSpec?.premise?.slice(0, 30);
      if (!title) { doDecompose(); return; }
      try {
        const saved = await loadState(title);
        if (saved && saved.step && saved.step !== S.loading) {
          if (saved.rawDecomp) setRawDecomp(saved.rawDecomp);
          if (saved.bookPlan) setBookPlan(saved.bookPlan);
          if (saved.styleVersions?.length) { setStyleVersions(saved.styleVersions); setStyleIdx(saved.styleIdx || 0); }
          else if (saved.styleSample) { setStyleVersions([saved.styleSample]); }
          if (saved.charSheets?.length) setCharSheets(saved.charSheets);
          if (saved.sbVersions?.length) { setSbVersions(saved.sbVersions); setSbIdx(saved.sbIdx || 0); }
          else if (saved.storyboardImg) { setSbVersions([saved.storyboardImg]); }
          if (saved.pageLayers?.length) setPageLayers(saved.pageLayers);
          if (saved.currentScene != null) setCurrentScene(saved.currentScene);
          if (saved.log) setLog(saved.log);
          addLog("Resumed saved session.");
          setStep(saved.step);
          return;
        }
      } catch { /* no usable cached decomposition; fall through to doDecompose() */ }
      doDecompose();
    })();
  }, []);

  const doDecompose = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setGenerating("Decomposing story...");
    try {
      addLog("Decomposing story...");
      const raw = await decomposeBook(bookSpec);
      setRawDecomp(raw);
      addLog(`"${raw.title}" — ${raw.scenes?.length || 0} scenes`);
      const plan = generateScenePlan(raw, bookSpec);
      setBookPlan(plan);
      addLog(`Plan ready: ${plan.scenes.length} scenes`);
      setStep(S.reviewStory);
    } catch (err) {
      addLog(`Decompose failed: ${err.message}`);
      setStep(S.reviewStory);
    } finally { busyRef.current = false; setGenerating(""); }
  };

  const genStyle = async () => {
    setGenerating("Generating style sample...");
    addLog("Generating style sample...");
    try {
      const img = await renderStyleSample(bookPlan.style_token, bookSpec.setting, (m) => { addLog(m); setGenerating(m); });
      setStyleVersions((prev) => { const n = [...prev, img]; setStyleIdx(n.length - 1); return n; });
      addLog("Style sample ready.");
    } catch (err) { addLog(`Style failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const genChar = async (charIndex) => {
    if (!bookPlan?.character_designs?.length) {
      addLog("No character designs available");
      return;
    }
    const designs = bookPlan.character_designs;
    const idx = charIndex != null ? charIndex : 0;
    const design = designs[idx];
    if (!design) return;
    const charName = bookSpec?.characters?.[idx]?.name || `Character ${idx + 1}`;
    setGenerating(`Generating character sheet for ${charName}...`);
    addLog(`Generating character sheet for ${charName}...`);
    try {
      const photos = bookSpec?.characters?.[idx]?.reference_photos || [];
      const refs = photos.length > 0
        ? [...photos, ...(curStyle ? [curStyle] : [])]
        : curStyle ? [curStyle] : undefined;
      const img = await renderCharacterReferences(design, bookPlan.style_token, (m) => { addLog(m); setGenerating(m); }, refs);
      setCharSheets((prev) => {
        const n = [...prev];
        while (n.length <= idx) n.push({ name: bookSpec?.characters?.[n.length]?.name || `Character ${n.length + 1}`, design: designs[n.length], versions: [], idx: 0 });
        const entry = { ...n[idx] };
        entry.versions = [...entry.versions, img];
        entry.idx = entry.versions.length - 1;
        n[idx] = entry;
        return n;
      });
      addLog(`${charName} sheet ready.`);
    } catch (err) { addLog(`${charName} failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const genAllChars = async () => {
    const designs = bookPlan?.character_designs || [];
    for (let i = 0; i < designs.length; i++) {
      await genChar(i);
    }
  };

  const genStoryboard = async () => {
    setGenerating("Generating storyboard...");
    addLog("Generating storyboard overview...");
    try {
      const img = await renderStoryboardOverview(bookPlan, (m) => { addLog(m); setGenerating(m); });
      setSbVersions((prev) => { const n = [...prev, img]; setSbIdx(n.length - 1); return n; });
      addLog("Storyboard ready.");
    } catch (err) { addLog(`Storyboard failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const startPages = async () => {
    const initial = bookPlan.scenes.map((scene) => ({
      scene_id: scene.id, title: scene.title, scene_type: scene.scene_type, page_text: scene.page_text,
      layers: buildPageLayers(scene, bookPlan), composite: null, approved: false,
    }));
    setPageLayers(initial);
    setCurrentScene(0);
    setStep(S.pages);
    addLog("Starting page drafts...");
    await genPageDrafts(0, initial);
  };

  const genPageDrafts = async (idx, layers) => {
    if (idx >= bookPlan.scenes.length || !layers[idx]) return;
    const page = layers[idx];
    setGenerating(`Page ${idx + 1}: generating layers...`);
    addLog(`Page ${idx + 1}: generating ${page.layers.length} draft layers...`);
    const updated = [...page.layers];
    for (let li = 0; li < updated.length; li++) {
      if (updated[li].type === "text") continue;
      if (updated[li].image_url && updated[li].quality !== "draft") continue;
      const label = `${updated[li].name} (page ${idx + 1})`;
      setGenerating(label + "...");
      addLog(`  ${label}...`);
      try {
        const url = await renderLayerDraft(updated[li].prompt, (m) => { addLog(m); setGenerating(m); }, null, updated[li].type);
        updated[li] = { ...updated[li], image_url: url, quality: "draft" };
      } catch (err) { addLog(`  ${updated[li].name} failed: ${err.message}`); }
    }
    const up = { ...page, layers: updated };
    const comp = await compositeScene(up, bookPlan.page_dims);
    setPageLayers((prev) => { const n = [...prev]; n[idx] = { ...up, composite: comp }; return n; });
    addLog(`Page ${idx + 1} drafts done.`);
    setGenerating("");
  };

  const bookKey = bookSpec?._storageKey || bookSpec?.title || bookSpec?.premise?.slice(0, 30) || "untitled";

  const retryLayer = async (pi, li) => {
    const page = pageLayers[pi]; if (!page) return;
    const layer = page.layers[li];
    setGenerating(`Retrying "${layer.name}"...`);
    addLog(`Retrying "${layer.name}"...`);
    try {
      const attempt = await logGenerationAttempt({ bookKey, sceneId: page.scene_id, layerId: layer.id, attemptType: "retry", prompt: layer.prompt, quality: "draft", verdict: "generated" });
      const url = await renderLayerDraft(layer.prompt, (m) => { addLog(m); setGenerating(m); }, null, layer.type);
      if (attempt?.id) await updateVerdict(attempt.id, url ? "generated" : "failed");
      const history = [...(layer.history || []), layer.image_url].filter(Boolean);
      const layers = [...page.layers]; layers[li] = { ...layer, image_url: url, quality: "draft", history, historyIdx: history.length, _attemptId: attempt?.id };
      const comp = await compositeScene({ ...page, layers }, bookPlan.page_dims);
      setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    } catch (err) { addLog(`Retry failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const upgradeLayer = async (pi, li) => {
    const page = pageLayers[pi]; if (!page) return;
    const layer = page.layers[li];
    setGenerating(`Upgrading "${layer.name}" to HQ...`);
    addLog(`Upgrading "${layer.name}" to final...`);
    try {
      const attempt = await logGenerationAttempt({ bookKey, sceneId: page.scene_id, layerId: layer.id, attemptType: "upgrade", prompt: layer.prompt, quality: "final", verdict: "pending" });
      const url = await renderLayerFinal(layer.prompt, (m) => { addLog(m); setGenerating(m); }, layer.image_url, layer.type);
      if (attempt?.id) await updateVerdict(attempt.id, url ? "generated" : "failed");
      const history = [...(layer.history || []), layer.image_url].filter(Boolean);
      const layers = [...page.layers]; layers[li] = { ...layer, image_url: url, quality: "final", history, historyIdx: history.length, _attemptId: attempt?.id };
      const comp = await compositeScene({ ...page, layers }, bookPlan.page_dims);
      setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    } catch (err) { addLog(`Upgrade failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const applyTransform = async () => {
    if (!transformingLayer) return;
    const { page: pi, layer: li } = transformingLayer;
    const page = pageLayers[pi]; const layer = page.layers[li];
    setGenerating(`Transforming "${layer.name}"...`);
    addLog(`Transforming "${layer.name}"...`);
    const history = [...(layer.history || []), layer.image_url].filter(Boolean);
    const layers = [...page.layers]; layers[li] = { ...layer, prompt: transformText, quality: "draft", history, historyIdx: history.length };
    try {
      const attempt = await logGenerationAttempt({ bookKey, sceneId: page.scene_id, layerId: layer.id, attemptType: "edit_prompt", prompt: transformText, quality: "draft", verdict: "pending" });
      const url = await renderLayerDraft(transformText, (m) => { addLog(m); setGenerating(m); }, null, layer.type);
      if (attempt?.id) await updateVerdict(attempt.id, url ? "generated" : "failed");
      layers[li] = { ...layers[li], image_url: url, _attemptId: attempt?.id };
    } catch (err) { addLog(`Transform failed: ${err.message}`); }
    const comp = await compositeScene({ ...page, layers }, bookPlan.page_dims);
    setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    setTransformingLayer(null); setTransformText("");
    setGenerating("");
  };

  const revertLayer = (pi, li, versionIdx) => {
    const page = pageLayers[pi]; if (!page) return;
    const layer = page.layers[li];
    const history = layer.history || [];
    if (versionIdx < 0 || versionIdx >= history.length) return;
    const url = history[versionIdx];
    const layers = [...page.layers];
    layers[li] = { ...layer, image_url: url, historyIdx: versionIdx };
    compositeScene({ ...page, layers }, bookPlan.page_dims).then((comp) => {
      setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    });
  };

  const approvePage = async (pi) => {
    const page = pageLayers[pi];
    for (const layer of page.layers) {
      if (layer._attemptId) {
        await updateVerdict(layer._attemptId, "accepted");
      }
    }
    let up = { ...page, approved: true };
    if (page.layers.every((l) => l.quality === "final") && !page.refined) {
      addLog("Running refinement...");
      try { const r = await refineScene(up, bookPlan.style_token, (m) => addLog(m)); up = { ...r, approved: true }; } catch (e) { addLog(`Refinement failed: ${e.message}`); }
    }
    setPageLayers((prev) => { const n = [...prev]; n[pi] = up; return n; });
    const next = pi + 1;
    if (next < bookPlan.scenes.length) {
      setCurrentScene(next);
      addLog(`Page ${pi + 1} approved. Next: page ${next + 1}.`);
      await genPageDrafts(next, pageLayers.map((p, i) => i === pi ? up : p));
    } else {
      setStep(S.done);
      addLog("All pages approved!");
    }
  };

  const updateBookPlan = (path, value) => {
    setBookPlan((prev) => {
      const n = { ...prev };
      const keys = path.split(".");
      let obj = n;
      for (let i = 0; i < keys.length - 1; i++) { obj[keys[i]] = { ...obj[keys[i]] }; obj = obj[keys[i]]; }
      obj[keys[keys.length - 1]] = value;
      return n;
    });
  };

  const updateScene = (idx, field, value) => {
    setRawDecomp((prev) => { const n = { ...prev }; n.scenes = [...n.scenes]; n.scenes[idx] = { ...n.scenes[idx], [field]: value }; return n; });
    if (bookPlan) {
      setBookPlan((prev) => { const n = { ...prev }; n.scenes = [...n.scenes]; if (n.scenes[idx]) n.scenes[idx] = { ...n.scenes[idx], [field]: value }; return n; });
    }
  };

  const handleReset = async () => {
    const title = bookSpec?._storageKey || bookSpec?.title || bookSpec?.premise?.slice(0, 30);
    if (title) await clearState(title);
    onReset();
  };

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    addLog("Exporting PDF...");
    try {
      await exportBookPdf({
        title: bookPlan?.title || bookSpec?.title || "My Book",
        pages: pageLayers,
        productId: "landscape_10x8",
        mode: "interior",
      });
      addLog("PDF downloaded!");
    } catch (err) {
      addLog(`Export failed: ${err.message}`);
    } finally {
      setExporting(false);
    }
  };

  const debounceLayoutSave = useCallback((page) => {
    if (!page?.scene_id) return;
    if (layoutSaveTimerRef.current) clearTimeout(layoutSaveTimerRef.current);
    layoutSaveTimerRef.current = setTimeout(() => {
      const layoutData = page.layers.map((l) => ({
        id: l.id, name: l.name, type: l.type, x: l.x, y: l.y,
        width: l.width, height: l.height, scale: l.scale, rotation: l.rotation,
        z_index: l.z_index, opacity: l.opacity, style: l.style, box: l.box,
        text_content: l.text_content,
      }));
      saveLayoutVersion({ bookKey, sceneId: page.scene_id, layout: layoutData });
    }, 2000);
  }, [bookKey]);

  const updatePageLayer = useCallback((_canvasId, layerId, changes) => {
    setPageLayers((prev) => {
      const pi = prev.findIndex((p) => p.layers?.some((l) => l.id === layerId));
      if (pi < 0) return prev;
      const page = prev[pi];
      const li = page.layers.findIndex((l) => l.id === layerId);
      if (li < 0) return prev;
      const layers = [...page.layers];
      layers[li] = { ...layers[li], ...changes };
      const comp = page.composite;
      const updated = prev.map((p, i) => i === pi ? { ...p, layers, composite: comp } : p);
      debounceLayoutSave(updated[pi]);
      return updated;
    });
  }, [debounceLayoutSave]);

  const updateLayerStyle = useCallback((layerId, styleChanges) => {
    setPageLayers((prev) => {
      const pi = prev.findIndex((p) => p.layers?.some((l) => l.id === layerId));
      if (pi < 0) return prev;
      const page = prev[pi];
      const li = page.layers.findIndex((l) => l.id === layerId);
      if (li < 0) return prev;
      const layers = [...page.layers];
      layers[li] = { ...layers[li], style: { ...(layers[li].style || DEFAULT_TEXT_STYLE), ...styleChanges } };
      const updated = prev.map((p, i) => i === pi ? { ...p, layers } : p);
      debounceLayoutSave(updated[pi]);
      return updated;
    });
  }, [debounceLayoutSave]);

  const updateLayerBox = useCallback((layerId, boxChanges) => {
    setPageLayers((prev) => {
      const pi = prev.findIndex((p) => p.layers?.some((l) => l.id === layerId));
      if (pi < 0) return prev;
      const page = prev[pi];
      const li = page.layers.findIndex((l) => l.id === layerId);
      if (li < 0) return prev;
      const layers = [...page.layers];
      layers[li] = { ...layers[li], box: { ...(layers[li].box || DEFAULT_BOX_STYLE), ...boxChanges } };
      const updated = prev.map((p, i) => i === pi ? { ...p, layers } : p);
      debounceLayoutSave(updated[pi]);
      return updated;
    });
  }, [debounceLayoutSave]);

  const curPage = pageLayers[currentScene];

  const STEP_ORDER = [S.reviewStory, S.reviewStyle, S.reviewCharacter, S.storyboard, S.pages];
  const STEP_LABELS = { [S.reviewStory]: "Story", [S.reviewStyle]: "Style", [S.reviewCharacter]: "Character", [S.storyboard]: "Board", [S.pages]: "Pages" };
  const stepIdx = STEP_ORDER.indexOf(step);
  const reachedStep = Math.max(stepIdx, pageLayers.length > 0 ? 4 : stepIdx);

  const stepNav = (
    <div style={{ display: "flex", gap: 2, padding: "6px 12px", background: "var(--ink-1)", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
      {STEP_ORDER.map((s, i) => {
        const active = s === step;
        const reachable = i <= reachedStep;
        return (
          <button key={s} onClick={() => reachable && setStep(s)} disabled={!reachable}
            style={{ flex: 1, padding: "6px 4px", fontSize: 11, fontFamily: "var(--font)", textTransform: "uppercase", letterSpacing: 1,
              background: active ? "var(--phosphor-bg)" : "transparent", borderColor: active ? "var(--phosphor)" : "transparent",
              color: active ? "var(--phosphor)" : reachable ? "var(--text-dim)" : "var(--ink-5)", borderRadius: 3, cursor: reachable ? "pointer" : "default" }}>
            {STEP_LABELS[s]}
          </button>
        );
      })}
    </div>
  );

  const genOverlay = generating ? (
    <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 200, background: "linear-gradient(to right, var(--ink-1), var(--ink-2))", borderTop: "2px solid var(--phosphor)", padding: "10px 24px", display: "flex", alignItems: "center", gap: 12 }}>
      <div className="status-dot generating" style={{ width: 12, height: 12, flexShrink: 0 }} />
      <div style={{ flex: 1 }}><div style={{ fontSize: 12, color: "var(--phosphor)", fontWeight: 600 }}>{generating}</div></div>
      <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font)" }}>generating...</div>
    </div>
  ) : null;

  // ── Loading ──────────────────────────────────────────────────────────────
  if (step === S.loading) {
    return <div className="main-layout">{genOverlay}<div className="viewport-area"><div className="empty-state">
      <div className="status-dot generating" style={{ width: 16, height: 16 }} />
      <div style={{ color: "var(--phosphor)", fontSize: 13 }}>Loading...</div>
    </div></div></div>;
  }

  // ── Step 1: Story ───────────────────────────────────────────────────────
  if (step === S.reviewStory && rawDecomp) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Story</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>Click any field to edit</div></div>
          <div className="scroll-area">
            {rawDecomp.scenes?.map((s, i) => (
              <div key={i} style={{ padding: "8px 12px", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--phosphor)", fontFamily: "var(--font)", width: 18 }}>{i + 1}</span>
                  <Editable value={s.title} onChange={(v) => updateScene(i, "title", v)} style={{ fontSize: 12, color: "var(--text)", flex: 1 }} />
                  <span style={{ color: "var(--text-dim)", fontSize: 9 }}>{s.type || s.scene_type}</span>
                </div>
                <Editable value={s.page_text} onChange={(v) => updateScene(i, "page_text", v)} multiline style={{ fontSize: 12, color: "var(--text)", marginTop: 2, lineHeight: 1.4 }} />
                <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 2, display: "flex", gap: 8 }}>
                  <span>pose: <Editable value={s.pose} onChange={(v) => updateScene(i, "pose", v)} style={{ fontSize: 10 }} /></span>
                  <span>comp: <Editable value={s.composition} onChange={(v) => updateScene(i, "composition", v)} style={{ fontSize: 10 }} /></span>
                </div>
              </div>
            ))}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={handleReset}>Start Over</button>
            <button style={{ flex: 1 }} onClick={doDecompose}>Regenerate</button>
            <button className="primary" style={{ flex: 1 }} onClick={() => setStep(S.reviewStyle)}>Continue</button>
          </div>
        </div>
        <div className="viewport-area" style={{ overflow: "auto" }}>
          <div style={{ maxWidth: 600, margin: "0 auto", padding: 32 }}>
            <h2 style={{ color: "var(--text)", fontSize: 22, marginBottom: 8 }}>{rawDecomp.title}</h2>
            {rawDecomp.dedication && <div style={{ color: "var(--text-dim)", fontSize: 13, fontStyle: "italic", marginBottom: 16 }}>For {rawDecomp.dedication}</div>}
            <div style={{ background: "var(--ink-2)", borderRadius: 6, padding: 16 }}>
              {(rawDecomp.scenes || []).map((s, i) => (
                <div key={i} style={{ padding: "6px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                  <span style={{ fontSize: 11, color: "var(--phosphor)", fontFamily: "var(--font)" }}>{i + 1}.</span>{" "}
                  <span style={{ fontSize: 13 }}>{s.title}</span>
                  {s.page_text && <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>"{s.page_text}"</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 2: Style ───────────────────────────────────────────────────────
  if (step === S.reviewStyle) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Style</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>Click any field to edit</div></div>
          <div className="scroll-area" style={{ padding: 12 }}>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Art style</b><Editable value={bookPlan?.style_token?.technique} onChange={(v) => updateBookPlan("style_token.technique", v)} multiline style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Edge</b><Editable value={bookPlan?.style_token?.edge_softness} onChange={(v) => updateBookPlan("style_token.edge_softness", v)} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Contrast</b><Editable value={bookPlan?.style_token?.contrast} onChange={(v) => updateBookPlan("style_token.contrast", v)} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Detail</b><Editable value={bookPlan?.style_token?.detail_level} onChange={(v) => updateBookPlan("style_token.detail_level", v)} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Mood</b><Editable value={bookSpec?.mood} onChange={(v) => { bookSpec.mood = v; }} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Lighting</b><Editable value={bookSpec?.lighting} onChange={(v) => { bookSpec.lighting = v; }} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}>
              <b style={{ fontSize: 11, color: "var(--text-dim)" }}>Character design</b>
              <Editable value={bookPlan?.character_design} onChange={(v) => updateBookPlan("character_design", v)} multiline style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.4 }} />
            </div>
            {styleVersions.length > 1 && (
              <div><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Versions ({styleVersions.length})</b>
              <VersionPicker versions={styleVersions} selectedIdx={styleIdx} onSelect={setStyleIdx} label="Style" /></div>
            )}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={genStyle}>Generate New</button>
            <button className="primary" style={{ flex: 1 }} onClick={() => setStep(S.reviewCharacter)}>Continue</button>
          </div>
        </div>
        <div className="viewport-area">
          {curStyle ? (
            <img src={curStyle} alt="Style sample" style={{ maxWidth: "90%", maxHeight: "90%", borderRadius: 6, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }} />
          ) : (
            <div className="empty-state">
              <div style={{ color: "var(--text-dim)", fontSize: 13 }}>No style sample yet. Click "Generate New".</div>
            </div>
          )}
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 3: Character ───────────────────────────────────────────────────
  if (step === S.reviewCharacter) {
    const allDesigns = bookPlan?.character_designs || [];
    const allChars = bookSpec?.characters || [];
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Characters ({allDesigns.length})</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>Generate reference sheets for each character</div></div>
          <div className="scroll-area" style={{ padding: 12 }}>
            {allDesigns.map((design, ci) => {
              const sheet = charSheets[ci];
              const name = allChars[ci]?.name || `Character ${ci + 1}`;
              const hasSheet = sheet?.versions?.length > 0;
              return (
                <div key={ci} style={{ marginBottom: 10, padding: 8, background: "var(--ink-2)", borderRadius: 4 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <div style={{ width: 24, height: 24, borderRadius: "50%", background: "var(--ink-3)", overflow: "hidden", flexShrink: 0 }}>
                      {allChars[ci]?.reference_photos?.[0] ? <img src={allChars[ci].reference_photos[0]} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--text-dim)" }}>{ci + 1}</div>}
                    </div>
                    <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>{name}</span>
                    <span style={{ fontSize: 9, color: "var(--text-dim)" }}>{allChars[ci]?.role || "character"}</span>
                    {hasSheet && <span style={{ fontSize: 9, color: "var(--phosphor)" }}>{sheet.versions.length} v</span>}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-dim)", maxHeight: 40, overflow: "auto", marginBottom: 4 }}>{design}</div>
                  <div style={{ display: "flex", gap: 4 }}>
                    <button style={{ flex: 1, fontSize: 10 }} onClick={() => genChar(ci)}>{hasSheet ? "Regenerate" : "Generate Sheet"}</button>
                    {sheet?.versions?.length > 1 && (
                      <VersionPicker versions={sheet.versions} selectedIdx={sheet.idx} onSelect={(vi) => setCharSheets((p) => { const n = [...p]; n[ci] = { ...n[ci], idx: vi }; return n; })} label={name} />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={genAllChars}>Generate All</button>
            <button className="primary" style={{ flex: 1 }} onClick={() => setStep(S.storyboard)}>Continue</button>
          </div>
        </div>
        <div className="viewport-area">
          {charSheets.some((s) => s?.versions?.length > 0) ? (
            <div style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "center", height: "100%", padding: 24, flexWrap: "wrap" }}>
              {charSheets.filter((s) => s?.versions?.length > 0).map((sheet, si) => (
                <div key={si} style={{ textAlign: "center" }}>
                  <img src={sheet.versions[sheet.idx]} alt={sheet.name} style={{ maxWidth: 300, maxHeight: 400, borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.5)" }} />
                  <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 4 }}>{sheet.name}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state"><div style={{ color: "var(--text-dim)", fontSize: 13 }}>No character sheets yet. Click "Generate All" or generate individually.</div></div>
          )}
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 4: Storyboard ──────────────────────────────────────────────────
  if (step === S.storyboard) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Storyboard</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>All scenes at a glance</div></div>
          <div className="scroll-area" style={{ padding: "8px 12px" }}>
            {bookPlan?.scenes.map((s, i) => (
              <div key={i} style={{ padding: "6px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                <span style={{ fontSize: 11, color: "var(--phosphor)", fontFamily: "var(--font)" }}>{i + 1}. {s.title}</span>
                <div style={{ fontSize: 10, color: "var(--text-dim)" }}>{s.scene_type}</div>
              </div>
            ))}
            {sbVersions.length > 1 && (
              <div style={{ marginTop: 8 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Versions ({sbVersions.length})</b>
              <VersionPicker versions={sbVersions} selectedIdx={sbIdx} onSelect={setSbIdx} label="Storyboard" /></div>
            )}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={genStoryboard}>Generate New</button>
            <button className="primary" style={{ flex: 1 }} onClick={startPages}>Start Pages</button>
          </div>
        </div>
        <div className="viewport-area">
          {curSb ? (
            <img src={curSb} alt="Storyboard" style={{ maxWidth: "90%", maxHeight: "90%", borderRadius: 6, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }} />
          ) : (
            <div className="empty-state"><div style={{ color: "var(--text-dim)", fontSize: 13 }}>No storyboard yet. Click "Generate New".</div></div>
          )}
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 5: Pages ───────────────────────────────────────────────────────
  if (step === S.pages || step === S.done) {
    const pageCanvas = bookPlan?.page_dims
      ? { id: curPage?.scene_id || "canvas", width: bookPlan.page_dims.w, height: bookPlan.page_dims.h, background_color: "#FFFFFF" }
      : null;
    const canvasLayers = (curPage?.layers || []).map((l) => ({
      ...l,
      image_path: l.image_url,
      visible: true,
      locked: false,
      opacity: l.opacity ?? 1,
      scale: l.scale ?? 1,
      rotation: l.rotation ?? 0,
    }));
    const selLayer = selectedLayerId ? curPage?.layers?.find((l) => l.id === selectedLayerId) : null;

    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section">
            <h3>Pages</h3>
            <div style={{ fontSize: 12, color: "var(--text)", marginBottom: 4 }}>{bookPlan?.title}</div>
            <div style={{ fontSize: 11, color: "var(--text-dim)" }}>{pageLayers.filter((p) => p.approved).length}/{pageLayers.length} approved</div>
            <div style={{ marginTop: 6, width: "100%", height: 3, background: "var(--ink-3)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ width: `${pageLayers.length ? (pageLayers.filter((p) => p.approved).length / pageLayers.length) * 100 : 0}%`, height: "100%", background: "var(--phosphor)", borderRadius: 2, transition: "width 0.3s" }} />
            </div>
          </div>
          <div className="scroll-area">
            {pageLayers.map((page, idx) => (
              <div key={idx} className={`layer-item ${idx === currentScene ? "selected" : ""}`} onClick={() => setCurrentScene(idx)} style={{ opacity: page.approved ? 0.7 : 1 }}>
                <div className="thumb" style={{ background: page.composite ? undefined : "var(--ink-3)" }}>
                  {page.composite ? <img src={page.composite} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <span>{idx + 1}</span>}
                </div>
                <div className="info">
                  <div className="name">{idx + 1}. {page.title}</div>
                  <div style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", gap: 4 }}>
                    <span>{page.scene_type}</span>
                    {page.approved && <span style={{ color: "var(--phosphor)" }}>ok</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="panel-section" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {step === S.done && (
              <button className="primary" style={{ width: "100%", fontSize: 13, padding: "10px 0" }} onClick={handleExport} disabled={exporting}>
                {exporting ? "Exporting..." : "Export PDF"}
              </button>
            )}
            <button style={{ width: "100%" }} onClick={handleReset}>Start Over</button>
          </div>
        </div>
        <div className="viewport-area">
          {pageCanvas && curPage ? (
            <CanvasViewport
              canvas={pageCanvas}
              layers={canvasLayers}
              selectedLayerId={selectedLayerId}
              onSelectLayer={setSelectedLayerId}
              onUpdateLayer={updatePageLayer}
            />
          ) : (
            <div className="empty-state"><div className="status-dot generating" style={{ width: 16, height: 16 }} /><div style={{ color: "var(--phosphor)", fontSize: 13 }}>Rendering...</div></div>
          )}
          <div style={{ position: "absolute", top: 12, right: 12, background: "var(--ink-2)", padding: "4px 10px", borderRadius: 4, fontSize: 11, fontFamily: "var(--font)", color: "var(--text-dim)" }}>Page {currentScene + 1} / {pageLayers.length}</div>
        </div>
        <div className="right-panel">
          <div className="panel-section scroll-area" style={{ flex: 1 }}>
            <h3>Layers</h3>
            {curPage ? (
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{curPage.title}</div>
                <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 3, background: "var(--ink-3)", color: "var(--phosphor)", fontFamily: "var(--font)" }}>{curPage.scene_type}</span>
                <div style={{ marginTop: 12 }}>
                  {(curPage.layers || []).map((layer, li) => (
                    <div key={layer.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 4px", background: selectedLayerId === layer.id ? "var(--phosphor-bg)" : "transparent", borderRadius: 4, marginBottom: 2, cursor: "pointer" }} onClick={() => setSelectedLayerId(layer.id)}>
                      <div style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, background: layer.type === "text" ? "var(--phosphor)" : layer.quality === "final" ? "var(--phosphor)" : layer.image_url ? "var(--amber)" : "var(--ink-5)" }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12 }}>{layer.name}</div>
                        <div style={{ fontSize: 10, color: "var(--text-dim)" }}>
                          {layer.type === "text" ? "canvas text" : layer.quality}
                        </div>
                      </div>
                      {layer.type !== "text" && (
                        <div style={{ display: "flex", gap: 2 }}>
                          <button style={{ fontSize: 9, padding: "1px 4px" }} onClick={(e) => { e.stopPropagation(); retryLayer(currentScene, li); }}>Retry</button>
                          <button style={{ fontSize: 9, padding: "1px 4px" }} onClick={(e) => { e.stopPropagation(); setTransformingLayer({ page: currentScene, layer: li }); setTransformText(layer.prompt); }}>Edit</button>
                          {layer.quality !== "final" && layer.image_url && (
                            <button style={{ fontSize: 9, padding: "1px 4px", color: "var(--phosphor)" }} onClick={(e) => { e.stopPropagation(); upgradeLayer(currentScene, li); }}>HQ</button>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {selLayer && selLayer.type === "text" && (
                  <div style={{ marginTop: 8, padding: 8, background: "var(--ink-2)", borderRadius: 4 }}>
                    <div style={{ fontSize: 10, color: "var(--text-dim)", marginBottom: 6, fontWeight: 600 }}>TEXT STYLE</div>
                    <div style={{ marginBottom: 6 }}>
                      <label style={{ fontSize: 10, color: "var(--text-dim)", display: "block", marginBottom: 2 }}>Font</label>
                      <select value={selLayer.style?.font_family || "Quicksand"} onChange={(e) => updateLayerStyle(selLayer.id, { font_family: e.target.value })} style={{ width: "100%", fontSize: 11 }}>
                        {GOOGLE_FONTS.map((f) => <option key={f} value={f}>{f}</option>)}
                      </select>
                    </div>
                    <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                      <div style={{ flex: 1 }}>
                        <label style={{ fontSize: 10, color: "var(--text-dim)", display: "block", marginBottom: 2 }}>Size</label>
                        <input type="number" value={selLayer.style?.font_size || 14} min={8} max={120} onChange={(e) => updateLayerStyle(selLayer.id, { font_size: parseInt(e.target.value) || 14 })} style={{ width: "100%", fontSize: 11 }} />
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <button style={{ fontSize: 10, padding: "2px 6px", fontWeight: selLayer.style?.font_weight === "bold" ? 700 : 400, background: selLayer.style?.font_weight === "bold" ? "var(--phosphor-bg)" : undefined }} onClick={() => updateLayerStyle(selLayer.id, { font_weight: selLayer.style?.font_weight === "bold" ? "normal" : "bold" })}>B</button>
                        <button style={{ fontSize: 10, padding: "2px 6px", fontStyle: selLayer.style?.font_style === "italic" ? "italic" : "normal", background: selLayer.style?.font_style === "italic" ? "var(--phosphor-bg)" : undefined }} onClick={() => updateLayerStyle(selLayer.id, { font_style: selLayer.style?.font_style === "italic" ? "normal" : "italic" })}>I</button>
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                      <div style={{ flex: 1 }}>
                        <label style={{ fontSize: 10, color: "var(--text-dim)", display: "block", marginBottom: 2 }}>Color</label>
                        <input type="color" value={selLayer.style?.color || "#333333"} onChange={(e) => updateLayerStyle(selLayer.id, { color: e.target.value })} style={{ width: "100%", height: 24, padding: 0, border: "1px solid var(--border)" }} />
                      </div>
                      <div style={{ flex: 1 }}>
                        <label style={{ fontSize: 10, color: "var(--text-dim)", display: "block", marginBottom: 2 }}>Align</label>
                        <select value={selLayer.style?.text_align || "center"} onChange={(e) => updateLayerStyle(selLayer.id, { text_align: e.target.value })} style={{ width: "100%", fontSize: 11 }}>
                          <option value="left">Left</option>
                          <option value="center">Center</option>
                          <option value="right">Right</option>
                        </select>
                      </div>
                    </div>
                    <div style={{ marginBottom: 6 }}>
                      <label style={{ fontSize: 10, color: "var(--text-dim)", display: "block", marginBottom: 2 }}>Line Height: {selLayer.style?.line_height || 1.4}</label>
                      <input type="range" min="0.8" max="3" step="0.1" value={selLayer.style?.line_height || 1.4} onChange={(e) => updateLayerStyle(selLayer.id, { line_height: parseFloat(e.target.value) })} style={{ width: "100%" }} />
                    </div>
                    <div style={{ marginBottom: 6 }}>
                      <label style={{ fontSize: 10, color: "var(--text-dim)", display: "block", marginBottom: 2 }}>Box Background</label>
                      <div style={{ display: "flex", gap: 4 }}>
                        <input type="color" value={(() => { const c = selLayer.box?.background_color || "rgba(255,255,255,0.85)"; return c.startsWith("#") ? c : "#ffffff"; })()} onChange={(e) => updateLayerBox(selLayer.id, { background_color: e.target.value })} style={{ width: 32, height: 24, padding: 0, border: "1px solid var(--border)" }} />
                        <button style={{ fontSize: 9, padding: "2px 6px" }} onClick={() => updateLayerBox(selLayer.id, { background_color: "transparent" })}>None</button>
                      </div>
                    </div>
                    <div style={{ marginBottom: 6 }}>
                      <label style={{ fontSize: 10, color: "var(--text-dim)", display: "block", marginBottom: 2 }}>Text Content</label>
                      <textarea value={selLayer.text_content || ""} onChange={(e) => updatePageLayer(null, selLayer.id, { text_content: e.target.value })} style={{ width: "100%", fontSize: 11, minHeight: 60 }} />
                    </div>
                  </div>
                )}
                {selLayer && selLayer.type !== "text" && (
                  <div style={{ marginTop: 8, padding: 8, background: "var(--ink-2)", borderRadius: 4 }}>
                    <div style={{ fontSize: 10, color: "var(--text-dim)", marginBottom: 4 }}>PROMPT</div>
                    <div style={{ fontSize: 11, lineHeight: 1.4, maxHeight: 80, overflow: "auto" }}>{selLayer.prompt}</div>
                    {selLayer.image_url && <img src={selLayer.image_url} alt="" style={{ width: "100%", marginTop: 6, borderRadius: 4 }} />}
                    {(selLayer.history?.length > 0) && (
                      <div style={{ marginTop: 6 }}>
                        <div style={{ fontSize: 10, color: "var(--text-dim)", marginBottom: 3 }}>VERSIONS ({selLayer.history.length} prior)</div>
                        <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                          {selLayer.history.map((hUrl, vi) => (
                            <div key={vi} onClick={() => revertLayer(currentScene, curPage.layers.indexOf(selLayer), vi)} style={{
                              width: 36, height: 36, borderRadius: 3, overflow: "hidden", cursor: "pointer",
                              border: "1px solid var(--border)", opacity: 0.7,
                            }}>
                              <img src={hUrl} alt={`v${vi}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {transformingLayer && transformingLayer.page === currentScene && (
                  <div style={{ marginTop: 8, padding: 8, background: "var(--ink-2)", borderRadius: 4, border: "1px solid var(--phosphor)" }}>
                    <div style={{ fontSize: 10, color: "var(--phosphor)", marginBottom: 4 }}>EDIT PROMPT</div>
                    <textarea autoFocus value={transformText} onChange={(e) => setTransformText(e.target.value)} style={{ width: "100%", fontSize: 11, minHeight: 60, marginBottom: 6 }} />
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="primary" style={{ flex: 1, fontSize: 11 }} onClick={applyTransform}>Apply</button>
                      <button style={{ flex: 1, fontSize: 11 }} onClick={() => setTransformingLayer(null)}>Cancel</button>
                    </div>
                  </div>
                )}
                {!curPage.approved && (
                  <button className="primary" style={{ width: "100%", fontSize: 12, marginTop: 12 }} onClick={() => approvePage(currentScene)}>
                    {currentScene < pageLayers.length - 1 ? "Approve & Next" : "Approve Final Page"}
                  </button>
                )}
                {curPage.approved && <div style={{ marginTop: 8, fontSize: 11, color: "var(--phosphor)", textAlign: "center" }}>Approved</div>}
              </div>
            ) : <p style={{ color: "var(--text-dim)", fontSize: 13 }}>No page selected</p>}
          </div>
          <div className="panel-section" style={{ flexShrink: 0, maxHeight: "30vh", overflowY: "auto", borderTop: "2px solid var(--phosphor)" }}>
            <h3>Log</h3>
            {log.slice(-15).map((m, i) => <div key={i} className="log-line" style={{ color: i === log.slice(-15).length - 1 ? "var(--phosphor)" : undefined }}>{m}</div>)}
          </div>
        </div>
      </div>
    );
  }

  // fallback
  return (
    <div className="main-layout">
      {genOverlay}
      <div className="viewport-area"><div className="empty-state">
        <div style={{ color: "var(--text-dim)", fontSize: 13 }}>Unexpected state: {step}</div>
        <button className="primary" onClick={handleReset}>Start Over</button>
        <button onClick={() => { if (rawDecomp) setStep(S.reviewStory); else doDecompose(); }}>Retry</button>
      </div></div>
    </div>
  );
}
