import { useState } from "react";

const STEPS = [
  { title: "Welcome to Hive", body: "Your AI-powered project management assistant. Let's get you set up in under 60 seconds.", icon: "🐝" },
  { title: "Chat with your PM", body: "Ask anything about your project. The AI has access to your Jira, Confluence, and team data.", icon: "💬" },
  { title: "Run DAGs", body: "Automated workflows that research, write, and optimize — all scored by evals.", icon: "🔄" },
  { title: "You're ready!", body: "The setup checklist on your Dashboard walks the rest: activate an LLM provider (admin), then switch to your daily-driver account for your first chat.", icon: "🚀" },
];

export function Onboarding({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0);
  const current = STEPS[step];

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9999 }} role="dialog" aria-modal="true" aria-label="Onboarding">
      <div style={{ background: "var(--paper)", borderRadius: 16, padding: 32, maxWidth: 400, width: "90%", textAlign: "center", boxShadow: "0 8px 32px rgba(0,0,0,0.2)" }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>{current.icon}</div>
        <h2 style={{ fontFamily: "var(--hand)", fontSize: 22, margin: "0 0 8px", color: "var(--ink)" }}>{current.title}</h2>
        <p style={{ fontFamily: "var(--hand)", fontSize: 14, color: "var(--pencil)", margin: "0 0 24px", lineHeight: 1.5 }}>{current.body}</p>

        {/* Progress dots */}
        <div style={{ display: "flex", justifyContent: "center", gap: 6, marginBottom: 20 }} aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((_, i) => (
            <div key={i} style={{ width: 8, height: 8, borderRadius: "50%", background: i <= step ? "var(--accent)" : "var(--rule)" }} />
          ))}
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
          {step > 0 && (
            <button onClick={() => setStep(s => s - 1)} style={{ padding: "8px 16px", borderRadius: 8, border: "1px solid var(--rule)", background: "var(--paper)", cursor: "pointer", fontFamily: "var(--hand)" }}>
              Back
            </button>
          )}
          {step < STEPS.length - 1 ? (
            <button onClick={() => setStep(s => s + 1)} className="btn-primary" style={{ padding: "8px 24px", borderRadius: 8, fontFamily: "var(--hand)", cursor: "pointer" }}>
              Next
            </button>
          ) : (
            <button onClick={() => { localStorage.setItem("hive_onboarded", "1"); onComplete(); }} className="btn-primary" style={{ padding: "8px 24px", borderRadius: 8, fontFamily: "var(--hand)", cursor: "pointer" }}>
              Get Started
            </button>
          )}
        </div>

        <button onClick={() => { localStorage.setItem("hive_onboarded", "1"); onComplete(); }} style={{ marginTop: 16, background: "none", border: "none", color: "var(--pencil)", cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10, textDecoration: "underline" }}>
          Skip onboarding
        </button>
      </div>
    </div>
  );
}
