import { useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { SecretField, TextField } from "../components/shared";

type Mode = "login" | "signup";

const USERNAME_RE = /^[a-zA-Z0-9_-]{3,32}$/;

function formatApiError(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg?: string }).msg ?? "");
        }
        return "";
      })
      .filter(Boolean);
    return parts.length > 0 ? parts.join("; ") : fallback;
  }
  return fallback;
}

const formShell: CSSProperties = {
  width: 320,
  background: "var(--paper)",
  border: "2px solid var(--ink)",
  borderRadius: 8,
  padding: "24px 20px",
  display: "flex",
  flexDirection: "column",
  gap: 14,
};

type LoginProps = {
  onAuthenticated: () => void | Promise<void>;
};

export default function Login({ onAuthenticated }: LoginProps) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setConfirmPassword("");
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(formatApiError(data.detail, "Login failed"));
      }
      await completeAuth();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function completeAuth() {
    await onAuthenticated();
    const whoRes = await fetch("/v1/auth/whoami", { credentials: "same-origin" });
    const whoData = await whoRes.json();
    if (!whoData.authenticated) {
      throw new Error("Session could not be established. Try signing in again.");
    }
    // Belt-and-suspenders: if the user landed on a stale URL (e.g. /pm/login
    // from a previous Sign-out redirect, or any non-route path), force the
    // SPA to the root so AuthGuard's child <Routes> can match `/` → Navigate
    // to /agents (PM mode) or /dashboard (engineering mode). Without this,
    // a stale /pm/login URL after re-login leaves the SPA with no matching
    // route → blank page.
    navigate("/", { replace: true });
  }

  async function handleSignup(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          username: username.trim(),
          password,
          confirm_password: confirmPassword,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(formatApiError(data.detail, "Signup failed"));
      }
      await completeAuth();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setLoading(false);
    }
  }

  const trimmedUsername = username.trim();
  const usernameValid = USERNAME_RE.test(trimmedUsername);
  const passwordValid = password.length >= 8;
  const passwordsMatch = password === confirmPassword;
  const signupValid = usernameValid && passwordValid && passwordsMatch;

  // Always tell the user why the submit button is disabled. Previously,
  // empty fields produced a greyed button with no hint at all — the user
  // saw "no message" and assumed signup was broken.
  const signupHint =
    mode !== "signup"
      ? null
      : !trimmedUsername
        ? "Pick a username (3–32 chars: letters, numbers, _ -)."
        : !usernameValid
          ? "Username must be 3–32 characters (letters, numbers, underscore, hyphen)."
          : !password
            ? "Pick a password (min 8 characters)."
            : !passwordValid
              ? "Password must be at least 8 characters."
              : !confirmPassword
                ? "Type your password again to confirm."
                : !passwordsMatch
                  ? "Passwords do not match."
                  : null;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#e9e3d3",
      }}
    >
      <div style={formShell}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontFamily: "var(--hand)", fontSize: 32, fontWeight: 700 }}>{"\uD83D\uDC1D"}</div>
          <div style={{ fontFamily: "var(--hand)", fontSize: 20, fontWeight: 600, marginTop: 4 }}>
            {"Hive Conductor"}
          </div>
          <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 2 }}>
            {mode === "login" ? "Sign in to your hive" : "Create a new account"}
          </div>
        </div>

        <div style={{ display: "flex", gap: 0, border: "1.3px solid var(--rule)", borderRadius: 4, overflow: "hidden" }}>
          <button
            type="button"
            className="btn"
            style={{
              flex: 1,
              borderRadius: 0,
              border: "none",
              background: mode === "login" ? "var(--accent)" : "transparent",
              color: mode === "login" ? "var(--paper)" : "var(--ink)",
              fontFamily: "var(--mono)",
              fontSize: 10,
            }}
            onClick={() => switchMode("login")}
          >
            Sign in
          </button>
          <button
            type="button"
            className="btn"
            style={{
              flex: 1,
              borderRadius: 0,
              border: "none",
              background: mode === "signup" ? "var(--accent)" : "transparent",
              color: mode === "signup" ? "var(--paper)" : "var(--ink)",
              fontFamily: "var(--mono)",
              fontSize: 10,
            }}
            onClick={() => switchMode("signup")}
          >
            Sign up
          </button>
        </div>

        {error && (
          <div
            style={{
              padding: "6px 10px",
              background: "rgba(196,69,42,0.12)",
              border: "1px solid var(--danger)",
              borderRadius: 4,
              fontFamily: "var(--mono)",
              fontSize: 9,
              color: "var(--danger)",
            }}
          >
            {error}
          </div>
        )}

        {mode === "login" ? (
          <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <TextField
              label="Username"
              value={username}
              onChange={setUsername}
              autoComplete="username"
              autoFocus
              required
            />
            <SecretField
              label="Password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              required
            />
            <button
              className="btn btn-accent"
              type="submit"
              disabled={loading || !username.trim() || !password}
              style={{ width: "100%", marginTop: 4 }}
            >
              {loading ? "signing in..." : "enter the hive"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleSignup} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {/* The rules move out of the placeholders and into hints. A
                placeholder holding "min 8 characters" vanishes the instant the
                user starts typing -- exactly when the rule matters. */}
            <TextField
              label="Username"
              value={username}
              onChange={setUsername}
              hint="Letters, numbers, _ and - only."
              autoComplete="username"
              autoFocus
              required
            />
            <SecretField
              label="Password"
              value={password}
              onChange={setPassword}
              hint="At least 8 characters."
              autoComplete="new-password"
              required
            />
            <SecretField
              label="Confirm password"
              value={confirmPassword}
              onChange={setConfirmPassword}
              autoComplete="new-password"
              required
            />
            {signupHint && (
              <div
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 9,
                  color: "var(--pencil)",
                  lineHeight: 1.4,
                }}
              >
                {signupHint}
              </div>
            )}
            <button
              className="btn btn-accent"
              type="submit"
              disabled={loading || !signupValid}
              style={{ width: "100%", marginTop: 4 }}
            >
              {loading ? "creating account..." : "create account"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
