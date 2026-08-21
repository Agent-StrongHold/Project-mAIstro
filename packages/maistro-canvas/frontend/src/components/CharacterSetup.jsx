import { useState, useRef } from "react";
import {
  extractCharacterSpec,
  generateCanonicalSheet,
  fileToBase64,
} from "../lib/bookApi";

export default function CharacterSetup({ onComplete }) {
  const [photos, setPhotos] = useState([]);
  const [spec, setSpec] = useState(null);
  const [sheet, setSheet] = useState(null);
  const [phase, setPhase] = useState(null);
  const [log, setLog] = useState([]);
  const fileRef = useRef();

  const addLog = (msg) => setLog((p) => [...p, msg]);

  const handleFiles = async (files) => {
    const newPhotos = [];
    for (const f of files) {
      const url = await fileToBase64(f);
      newPhotos.push({ file: f, url, name: f.name });
    }
    setPhotos((p) => [...p, ...newPhotos].slice(0, 10));
  };

  const handleAnalyze = async () => {
    setPhase("analyzing");
    addLog("Analyzing photos...");
    try {
      const urls = photos.map((p) => p.url);
      const characterSpec = await extractCharacterSpec(urls);
      setSpec(characterSpec);
      addLog(`Extracted: ${characterSpec.hair}, ${characterSpec.eye_color} eyes, ${characterSpec.face_shape} face`);
    } catch (err) {
      addLog(`Error: ${err.message}`);
    }
    setPhase(null);
  };

  const handleGenerateSheet = async () => {
    setPhase("generating");
    addLog("Generating canonical character sheet...");
    try {
      const style = {
        art_style: "warm watercolor childrens book illustration, soft edges, gentle shading",
        color_palette: ["#F4A460", "#DEB887", "#87CEEB", "#90EE90", "#FFD700"],
        lighting: "soft warm natural light",
      };
      const result = await generateCanonicalSheet(spec, style);
      setSheet(result);
      addLog("Character sheet complete! 4 views generated.");
    } catch (err) {
      addLog(`Error: ${err.message}`);
    }
    setPhase(null);
  };

  const sheetViews = sheet
    ? [
        { key: "front_view", label: "Front" },
        { key: "three_quarter_view", label: "3/4" },
        { key: "side_profile", label: "Side" },
        { key: "expressions", label: "Expressions" },
      ]
    : [];

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <div
        style={{
          flex: 1,
          padding: 32,
          overflow: "auto",
          borderRight: "1px solid var(--border)",
        }}
      >
        <h2 style={{ fontFamily: "var(--font)", color: "var(--phosphor)", fontSize: 16, marginBottom: 4 }}>
          STEP 1: CHARACTER SETUP
        </h2>
        <p style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 20 }}>
          Upload 3-10 photos of the child. We will create a canonical character
          sheet in your book illustration style.
        </p>

        <div
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            handleFiles(Array.from(e.dataTransfer.files));
          }}
          style={{
            border: "2px dashed var(--border)",
            borderRadius: 8,
            padding: 24,
            textAlign: "center",
            cursor: "pointer",
            marginBottom: 16,
            transition: "border-color 0.15s",
          }}
        >
          <div style={{ fontSize: 28, opacity: 0.3, marginBottom: 8 }}>+</div>
          <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
            Drop photos here or click to browse
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            multiple
            style={{ display: "none" }}
            onChange={(e) => handleFiles(Array.from(e.target.files))}
          />
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
          {photos.map((p, i) => (
            <div key={i} style={{ position: "relative" }}>
              <img
                src={p.url}
                alt=""
                style={{
                  width: 80,
                  height: 80,
                  objectFit: "cover",
                  borderRadius: 6,
                  border: "1px solid var(--border)",
                }}
              />
              <button
                style={{
                  position: "absolute",
                  top: -6,
                  right: -6,
                  width: 20,
                  height: 20,
                  padding: 0,
                  fontSize: 11,
                  background: "var(--burn)",
                  color: "white",
                  border: "none",
                  borderRadius: 10,
                  cursor: "pointer",
                }}
                onClick={() => setPhotos((ps) => ps.filter((_, j) => j !== i))}
              >
                x
              </button>
            </div>
          ))}
        </div>

        {photos.length >= 3 && !spec && (
          <button
            className="primary"
            style={{ width: "100%" }}
            disabled={phase === "analyzing"}
            onClick={handleAnalyze}
          >
            {phase === "analyzing" ? "Analyzing..." : "Analyze Character"}
          </button>
        )}

        {spec && (
          <div style={{ marginTop: 16 }}>
            <h3 style={{ fontFamily: "var(--font)", fontSize: 12, color: "var(--phosphor)", marginBottom: 8 }}>
              CHARACTER SPEC
            </h3>
            <div
              style={{
                background: "var(--ink-2)",
                borderRadius: 6,
                padding: 12,
                fontSize: 12,
                color: "var(--text)",
              }}
            >
              {Object.entries(spec).map(([k, v]) => (
                <div key={k} style={{ marginBottom: 4 }}>
                  <span style={{ color: "var(--text-dim)" }}>{k.replace(/_/g, " ")}:</span>{" "}
                  {Array.isArray(v) ? v.join(", ") : String(v)}
                </div>
              ))}
            </div>

            {!sheet && (
              <button
                className="primary"
                style={{ width: "100%", marginTop: 12 }}
                disabled={phase === "generating"}
                onClick={handleGenerateSheet}
              >
                {phase === "generating" ? "Generating sheet..." : "Generate Canonical Sheet"}
              </button>
            )}
          </div>
        )}

        {log.length > 0 && (
          <div
            style={{
              marginTop: 12,
              fontFamily: "var(--font)",
              fontSize: 11,
              color: "var(--text-dim)",
              background: "var(--ink-2)",
              borderRadius: 4,
              padding: 8,
            }}
          >
            {log.map((msg, i) => (
              <div
                key={i}
                style={{
                  color: msg.startsWith("Error")
                    ? "var(--burn)"
                    : i === log.length - 1
                      ? "var(--phosphor)"
                      : undefined,
                }}
              >
                {msg}
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ width: 400, padding: 32, overflow: "auto" }}>
        <h2 style={{ fontFamily: "var(--font)", fontSize: 16, color: "var(--phosphor)", marginBottom: 16 }}>
          CANONICAL CHARACTER SHEET
        </h2>

        {sheet ? (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {sheetViews.map(({ key, label }) => (
                <div key={key}>
                  <div
                    style={{
                      fontSize: 10,
                      fontFamily: "var(--font)",
                      color: "var(--text-dim)",
                      marginBottom: 4,
                      textTransform: "uppercase",
                    }}
                  >
                    {label}
                  </div>
                  <img
                    src={sheet[key]}
                    alt={label}
                    style={{
                      width: "100%",
                      borderRadius: 6,
                      border: "1px solid var(--border)",
                      background: "white",
                    }}
                  />
                </div>
              ))}
            </div>
            <button
              className="primary"
              style={{ width: "100%", marginTop: 16, padding: "10px 0" }}
              onClick={() => onComplete(spec, sheet)}
            >
              Use This Character
            </button>
          </>
        ) : (
          <div style={{ color: "var(--text-dim)", fontSize: 13, textAlign: "center", marginTop: 40 }}>
            Upload photos and generate the sheet to preview here
          </div>
        )}
      </div>
    </div>
  );
}
