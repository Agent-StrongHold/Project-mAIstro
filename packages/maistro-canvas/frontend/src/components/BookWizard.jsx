import { useState, useEffect } from "react";
import { listTemplates, saveTemplate, deleteTemplate } from "../lib/templates";
import { listCharacters, saveCharacter, deleteCharacter } from "../lib/characters";
import { extractFeaturesFromPhotos } from "../lib/featureExtractor";

const CHAR_FIELDS = [
  { key: "name", label: "Name", placeholder: "e.g. Emma" },
  { key: "age", label: "Age range", type: "select", options: ["3-4", "5-6", "7-8", "9-10", "11-12", "12-14"] },
  { key: "pronouns", label: "Pronouns", type: "select", options: ["she/her", "he/him", "they/them"] },
  { key: "nickname", label: "Nickname (optional)", placeholder: "e.g. Em" },
  { key: "hair", label: "Hair", placeholder: "e.g. curly brown, shoulder length" },
  { key: "skin_tone", label: "Skin tone", placeholder: "e.g. warm brown, fair with freckles" },
  { key: "eye_color", label: "Eye color", placeholder: "e.g. hazel, dark brown" },
  { key: "face_shape", label: "Face shape", type: "select", options: ["round", "oval", "heart-shaped", "square"] },
  { key: "signature_features", label: "Distinctive features", placeholder: "e.g. gap tooth, dimple, glasses" },
  { key: "build", label: "Build", placeholder: "e.g. tall for age, petite" },
  { key: "role", label: "Role in story", type: "select", options: ["main character", "best friend / sidekick", "sibling", "pet / companion", "other"] },
];

const STEPS = [
  { key: "characters", title: "Who is in the story?", helper: "Add your recurring characters. Save them to reuse in other books." },
  { key: "style", title: "Illustration style", helper: "Sets the visual look for the entire book",
    fields: [
      { key: "art_style", label: "Art style", type: "select", options: ["Warm watercolor childrens book", "Soft pastel digital illustration", "Bold gouache with visible brushstrokes", "Gentle colored pencil sketch", "Clean flat vector illustration", "Whimsical ink and wash", "Dreamy airbrushed fantasy"] },
      { key: "mood", label: "Overall mood", type: "select", options: ["warm and cozy", "bright and adventurous", "dreamy and magical", "playful and silly", "calm and gentle", "exciting and energetic"] },
      { key: "palette_preference", label: "Color preference", type: "select", options: ["warm earth tones (browns, oranges, golds)", "soft pastels (pinks, lavenders, mint)", "bright and saturated (reds, blues, greens)", "cool ocean tones (teals, blues, silver)", "nature greens and woodland tones", "let the AI choose"] },
      { key: "lighting", label: "Lighting feel", type: "select", options: ["soft golden hour warmth", "bright cheerful daylight", "moonlit and sparkly", "dappled forest light", "cozy lamplight glow", "natural and neutral"] },
    ],
  },
  { key: "story", title: "What is the story?", helper: "Describe the adventure",
    fields: [
      { key: "premise", label: "Story premise (1-3 sentences)", type: "textarea", required: true, placeholder: "e.g. A girl discovers a hidden door in her grandmother's garden..." },
      { key: "setting", label: "Where does it take place?", placeholder: "e.g. A magical forest, a castle in the clouds" },
      { key: "lessons", label: "Lesson or theme (optional)", placeholder: "e.g. Courage, friendship, it's okay to be different" },
      { key: "ending", label: "How should it end?", type: "select", options: ["happy and triumphant", "cozy and heartwarming", "surprise twist", "open-ended", "let the AI decide"] },
    ],
  },
  { key: "book", title: "Book details", helper: "Final settings",
    fields: [
      { key: "page_count", label: "Pages/spreads", type: "select", options: ["8 (short)", "12 (standard)", "16 (long)", "20 (epic)"] },
      { key: "orientation", label: "Orientation", type: "select", options: ["landscape (wide)", "portrait (tall)", "square"] },
      { key: "title", label: "Book title (or let AI create one)", placeholder: "e.g. Emma and the Whispering Woods" },
      { key: "dedication", label: "Dedication (optional)", placeholder: "e.g. For Emma, who always looks for magic" },
    ],
  },
];

function CharacterCard({ char, onChange, onRemove, index, onSaveChar }) {
  const [expanded, setExpanded] = useState(index === 0);
  const [saved, setSaved] = useState(false);

  const handlePhotoUpload = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    const maxPhotos = 5;
    const currentPhotos = char.reference_photos || [];
    const toProcess = files.slice(0, maxPhotos - currentPhotos.length);
    let loaded = 0;
    const newPhotos = [];
    toProcess.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        newPhotos.push(ev.target.result);
        loaded++;
        if (loaded === toProcess.length) {
          const allPhotos = [...currentPhotos, ...newPhotos];
          onChange("reference_photos", allPhotos);
          extractFeaturesFromPhotos(allPhotos).then((features) => {
            if (!features) return;
            if (features.hair_color) onChange("hair", features.hair_color);
            if (features.skin_tone) onChange("skin_tone", features.skin_tone);
            if (features.eye_color) onChange("eye_color", features.eye_color);
          });
        }
      };
      reader.readAsDataURL(file);
    });
  };

  const removePhoto = (photoIdx) => {
    const photos = [...(char.reference_photos || [])];
    photos.splice(photoIdx, 1);
    onChange("reference_photos", photos);
  };

  const handleSave = async () => {
    if (!char.name?.trim()) return;
    await saveCharacter({ ...char });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    if (onSaveChar) onSaveChar();
  };

  return (
    <div style={{ background: "var(--ink-1)", border: "1px solid var(--border)", borderRadius: 6, marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", cursor: "pointer" }} onClick={() => setExpanded(!expanded)}>
        <div style={{ width: 28, height: 28, borderRadius: "50%", background: "var(--ink-3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, color: "var(--phosphor)", fontFamily: "var(--font)", flexShrink: 0, overflow: "hidden" }}>
          {(char.reference_photos || []).length > 0 ? (
            <img src={char.reference_photos[0]} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : (
            index + 1
          )}
        </div>
        <div style={{ flex: 1, fontSize: 14, fontWeight: 600 }}>{char.name || `Character ${index + 1}`}</div>
        <span style={{ fontSize: 10, color: "var(--text-dim)" }}>{char.role || "main character"}</span>
        {(char.reference_photos || []).length > 0 && <span style={{ fontSize: 10, color: "var(--phosphor)" }}>{char.reference_photos.length} photo{char.reference_photos.length > 1 ? "s" : ""}</span>}
        <button style={{ fontSize: 10, padding: "2px 8px", border: "none", background: "transparent", color: "var(--text-dim)" }} onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}>{expanded ? "collapse" : "expand"}</button>
        {onRemove && <button className="danger" style={{ fontSize: 10, padding: "2px 8px" }} onClick={(e) => { e.stopPropagation(); onRemove(); }}>Remove</button>}
      </div>
      {expanded && (
        <div style={{ padding: "4px 12px 12px" }}>
          <div style={{ marginBottom: 10, padding: 8, background: "var(--ink-2)", borderRadius: 4 }}>
            <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 4 }}>Reference photos (3-5 photos of the child for personalized character)</div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {(char.reference_photos || []).map((photo, pi) => (
                <div key={pi} style={{ width: 56, height: 56, borderRadius: 4, overflow: "hidden", position: "relative", border: "1px solid var(--border)" }}>
                  <img src={photo} alt={`ref ${pi + 1}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  <button onClick={() => removePhoto(pi)} style={{ position: "absolute", top: 1, right: 1, width: 14, height: 14, fontSize: 8, padding: 0, background: "rgba(0,0,0,0.7)", color: "var(--text)", border: "none", borderRadius: 2, cursor: "pointer", lineHeight: "14px" }}>x</button>
                </div>
              ))}
              {(char.reference_photos || []).length < 5 && (
                <label style={{ width: 56, height: 56, borderRadius: 4, border: "2px dashed var(--border)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 18, color: "var(--text-dim)" }}>
                  +
                  <input type="file" accept="image/*" multiple onChange={handlePhotoUpload} style={{ display: "none" }} />
                </label>
              )}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>
              {(char.reference_photos || []).length === 0
                ? "No photos — character will be text-described only"
                : `${(char.reference_photos || []).length}/5 uploaded`}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {CHAR_FIELDS.map((f) => (
              <div key={f.key} style={{ gridColumn: f.type === "select" || f.key === "name" ? "span 1" : "span 2" }}>
                <label style={{ display: "block", fontSize: 11, color: "var(--text-dim)", marginBottom: 2 }}>{f.label}</label>
                {f.type === "select" ? (
                  <select value={char[f.key] || ""} onChange={(e) => onChange(f.key, e.target.value)} style={{ width: "100%", fontSize: 12 }}>
                    <option value="">Choose...</option>
                    {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input value={char[f.key] || ""} onChange={(e) => onChange(f.key, e.target.value)} placeholder={f.placeholder} style={{ width: "100%", fontSize: 12 }} />
                )}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 8, display: "flex", justifyContent: "flex-end" }}>
            <button onClick={handleSave} disabled={!char.name?.trim()} style={{ fontSize: 11 }}>
              {saved ? "Saved!" : "Save Character"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function TemplatePicker({ templates, onDelete, onAddChar, onReplaceAll }) {
  const [expanded, setExpanded] = useState(null);

  if (templates.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      {templates.map((t) => (
        <div key={t.key} style={{ background: "var(--ink-2)", border: "1px solid var(--border)", borderRadius: 4, marginBottom: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px" }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>{t.name}</span>
            <span style={{ fontSize: 10, color: "var(--text-dim)" }}>({(t.characters || []).length} chars)</span>
            <div style={{ flex: 1 }} />
            <button style={{ fontSize: 10, padding: "2px 6px" }} onClick={() => setExpanded(expanded === t.key ? null : t.key)}>
              {expanded === t.key ? "close" : "pick chars"}
            </button>
            <button style={{ fontSize: 9, padding: "2px 6px", color: "var(--text-dim)" }} onClick={() => onReplaceAll(t)}>Replace All</button>
            <button className="danger" style={{ fontSize: 9, padding: "1px 4px" }} onClick={async () => { await deleteTemplate(t.key); onDelete(); }}>x</button>
          </div>
          {expanded === t.key && (
            <div style={{ padding: "4px 10px 8px", borderTop: "1px solid var(--border)" }}>
              {(t.characters || []).map((c, ci) => (
                <div key={ci} style={{ display: "flex", alignItems: "center", gap: 6, padding: "3px 0" }}>
                  <div style={{ width: 20, height: 20, borderRadius: "50%", background: "var(--ink-3)", overflow: "hidden", flexShrink: 0 }}>
                    {(c.reference_photos || []).length > 0 ? (
                      <img src={c.reference_photos[0]} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    ) : (
                      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, color: "var(--text-dim)" }}>{ci + 1}</div>
                    )}
                  </div>
                  <span style={{ fontSize: 11, flex: 1 }}>{c.name || `Char ${ci + 1}`}</span>
                  <span style={{ fontSize: 9, color: "var(--text-dim)" }}>{c.role}</span>
                  <button className="primary" style={{ fontSize: 9, padding: "1px 6px" }} onClick={() => onAddChar(c)}>+ Add</button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function SavedCharactersDrawer({ savedChars, onDelete, onAddChar }) {
  const [open, setOpen] = useState(false);

  if (savedChars.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <button onClick={() => setOpen(!open)} style={{ fontSize: 12, width: "100%", marginBottom: 4 }}>
        {open ? "Hide Saved Characters" : `Saved Characters (${savedChars.length})`}
      </button>
      {open && (
        <div style={{ background: "var(--ink-2)", borderRadius: 4, padding: 6, border: "1px solid var(--border)" }}>
          {savedChars.map((c) => (
            <div key={c.key} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 2px", borderBottom: "1px solid var(--ink-3)" }}>
              <div style={{ width: 22, height: 22, borderRadius: "50%", background: "var(--ink-3)", overflow: "hidden", flexShrink: 0 }}>
                {(c.reference_photos || []).length > 0 ? (
                  <img src={c.reference_photos[0]} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--text-dim)" }}>{(c.name || "?")[0]}</div>
                )}
              </div>
              <span style={{ fontSize: 11, flex: 1 }}>{c.name || c.key}</span>
              <span style={{ fontSize: 9, color: "var(--text-dim)" }}>{c.role || "—"}</span>
              <button className="primary" style={{ fontSize: 9, padding: "1px 6px" }} onClick={() => onAddChar(c)}>+ Add</button>
              <button className="danger" style={{ fontSize: 9, padding: "1px 4px" }} onClick={async () => { await deleteCharacter(c.key); onDelete(); }}>x</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function BookWizard({ onComplete }) {
  const [step, setStep] = useState(0);
  const [characters, setCharacters] = useState([{ name: "", role: "main character" }]);
  const [styleData, setStyleData] = useState({});
  const [storyData, setStoryData] = useState({});
  const [bookData, setBookData] = useState({});
  const [templates, setTemplates] = useState([]);
  const [savedChars, setSavedChars] = useState([]);
  const [templateName, setTemplateName] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);
  const [dupNotice, setDupNotice] = useState("");

  const refreshTemplates = () => listTemplates().then(setTemplates);
  const refreshSavedChars = () => listCharacters().then(setSavedChars);

  useEffect(() => { refreshTemplates(); refreshSavedChars(); }, []);

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;
  const stepData = step === 0 ? {} : step === 1 ? styleData : step === 2 ? storyData : bookData;
  const setStepData = step === 1 ? setStyleData : step === 2 ? setStoryData : setBookData;

  const setField = (key, value) => setStepData((d) => ({ ...d, [key]: value }));

  const addCharacter = () => setCharacters((p) => [...p, { name: "", role: "sidekick" }]);

  const addCharacterFromSource = (charData) => {
    const name = (charData.name || "").trim().toLowerCase();
    if (name && characters.some((c) => (c.name || "").trim().toLowerCase() === name)) {
      setDupNotice(`"${charData.name}" is already added`);
      setTimeout(() => setDupNotice(""), 3000);
      return;
    }
    setCharacters((p) => [...p, { ...charData, reference_photos: charData.reference_photos || [] }]);
  };

  const updateCharacter = (idx, key, value) => {
    setCharacters((p) => { const n = [...p]; n[idx] = { ...n[idx], [key]: value }; return n; });
  };

  const removeCharacter = (idx) => setCharacters((p) => p.filter((_, i) => i !== idx));

  const handleSaveTemplate = async () => {
    if (!templateName.trim()) return;
    const tmpl = { name: templateName, characters, style: styleData, savedAt: new Date().toISOString() };
    await saveTemplate(tmpl);
    await refreshTemplates();
    setTemplateName("");
  };

  const handleReplaceAll = (tmpl) => {
    setCharacters(tmpl.characters || [{ name: "", role: "main character" }]);
    if (tmpl.style) setStyleData((d) => ({ ...d, ...tmpl.style }));
  };

  const handleComplete = () => {
    const mainChar = characters.find((c) => c.role === "main character") || characters[0] || {};
    onComplete({
      ...mainChar,
      characters,
      ...styleData,
      ...storyData,
      ...bookData,
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", maxWidth: 640, margin: "0 auto", padding: "24px 16px" }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 24 }}>
        {STEPS.map((_, i) => (
          <div key={i} style={{ flex: 1, height: 3, borderRadius: 2, background: i <= step ? "var(--phosphor)" : "var(--ink-3)" }} />
        ))}
      </div>

      <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 4 }}>Step {step + 1} of {STEPS.length}</div>
      <h2 style={{ fontFamily: "var(--font)", fontSize: 20, color: "var(--phosphor)", marginBottom: 4 }}>{current.title}</h2>
      <p style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 20 }}>{current.helper}</p>

      <div style={{ flex: 1, overflow: "auto" }}>
        {step === 0 ? (
          <>
            <SavedCharactersDrawer
              savedChars={savedChars}
              onDelete={refreshSavedChars}
              onAddChar={addCharacterFromSource}
            />
            {templates.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <button onClick={() => setShowTemplates(!showTemplates)} style={{ fontSize: 12, width: "100%", marginBottom: 4 }}>
                  {showTemplates ? "Hide Templates" : `Templates (${templates.length})`}
                </button>
                {showTemplates && (
                  <TemplatePicker
                    templates={templates}
                    onDelete={refreshTemplates}
                    onAddChar={addCharacterFromSource}
                    onReplaceAll={handleReplaceAll}
                  />
                )}
              </div>
            )}
            {dupNotice && (
              <div style={{ fontSize: 11, color: "var(--amber)", marginBottom: 8, padding: "4px 8px", background: "rgba(255,170,0,0.1)", borderRadius: 4 }}>{dupNotice}</div>
            )}
            {characters.map((char, idx) => (
              <CharacterCard key={idx} char={char} index={idx}
                onChange={(key, val) => updateCharacter(idx, key, val)}
                onRemove={characters.length > 1 ? () => removeCharacter(idx) : null}
                onSaveChar={refreshSavedChars}
              />
            ))}
            <button onClick={addCharacter} style={{ width: "100%", marginTop: 4, marginBottom: 16 }}>+ Add Character</button>
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>Save all characters as a template for reuse:</div>
              <div style={{ display: "flex", gap: 8 }}>
                <input value={templateName} onChange={(e) => setTemplateName(e.target.value)} placeholder="Template name" style={{ flex: 1, fontSize: 12 }} />
                <button onClick={handleSaveTemplate} disabled={!templateName.trim()}>Save Template</button>
              </div>
            </div>
          </>
        ) : (
          (current.fields || []).map((field) => (
            <div key={field.key} style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)", marginBottom: 4 }}>
                {field.label}{field.required ? " *" : ""}
              </label>
              {field.type === "textarea" ? (
                <textarea value={stepData[field.key] || ""} onChange={(e) => setField(field.key, e.target.value)} placeholder={field.placeholder} rows={4} style={{ width: "100%" }} />
              ) : field.type === "select" ? (
                <select value={stepData[field.key] || ""} onChange={(e) => setField(field.key, e.target.value)} style={{ width: "100%" }}>
                  <option value="">Choose...</option>
                  {field.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              ) : (
                <input value={stepData[field.key] || ""} onChange={(e) => setField(field.key, e.target.value)} placeholder={field.placeholder} style={{ width: "100%" }} />
              )}
            </div>
          ))
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
        {step > 0 && <button onClick={() => setStep(step - 1)}>Back</button>}
        <div style={{ flex: 1 }} />
        {isLast ? (
          <button className="primary" onClick={handleComplete}>Build My Book</button>
        ) : (
          <button className="primary" onClick={() => setStep(step + 1)}>Next</button>
        )}
      </div>
    </div>
  );
}
