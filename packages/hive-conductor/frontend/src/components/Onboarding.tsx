import { useState } from "react";
import { Modal } from "./shared";

const STEPS = [
  { title: "Welcome to Hive", body: "Your AI-powered project management assistant. Let's get you set up in under 60 seconds.", icon: "🐝" },
  { title: "Chat with your PM", body: "Ask anything about your project. The AI has access to your Jira, Confluence, and team data.", icon: "💬" },
  { title: "Run DAGs", body: "Automated workflows that research, write, and optimize — all scored by evals.", icon: "🔄" },
  { title: "You're ready!", body: "The setup checklist on your Dashboard walks the rest: activate an LLM provider (admin), then switch to your daily-driver account for your first chat.", icon: "🚀" },
];

export function Onboarding({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0);
  const current = STEPS[step];

  const dismiss = () => { localStorage.setItem("hive_onboarded", "1"); onComplete(); };

  return (
    // The shared Modal, not a hand-rolled overlay (#371). This was a
    // fixed-position <div> carrying `role="dialog"` on the *backdrop* rather
    // than on the panel, with no focus management and no Escape — the first
    // thing a new user meets, and it left every control on the page behind it
    // in the tab order. Escape and the ✕ both take the "Skip onboarding" path
    // this dialog already offered, so nothing is lost by leaving.
    <Modal open onClose={dismiss} title={current.title}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>{current.icon}</div>
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
            <button onClick={dismiss} className="btn-primary" style={{ padding: "8px 24px", borderRadius: 8, fontFamily: "var(--hand)", cursor: "pointer" }}>
              Get Started
            </button>
          )}
        </div>

        <button onClick={dismiss} style={{ marginTop: 16, background: "none", border: "none", color: "var(--pencil)", cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10, textDecoration: "underline" }}>
          Skip onboarding
        </button>
      </div>
    </Modal>
  );
}
