import { useEffect, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";

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

const labelStyle: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  color: "var(--pencil)",
  marginBottom: 3,
};

type LoginProps = {
  onAuthenticated: () => void | Promise<void>;
};

export default function Login({ onAuthenticated }: LoginProps) {
  const navigate = useNavigate();
  const [inviteToken] = useState(
    () => new URLSearchParams(window.location.search).get("invite") ?? "",
  );
  const [mode, setMode] = useState<Mode>(inviteToken ? "signup" : "login");
  const [registrationAvailable, setRegistrationAvailable] = useState(Boolean(inviteToken));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    void fetch("/v1/setup/registration-policy", { credentials: "same-origin" })
      .then(async (res) => {
        if (!res.ok) throw new Error("registration policy unavailable");
        return (await res.json()) as { mode?: string };
      })
      .then((policy) => {
        if (!active) return;
        const available = policy.mode === "open" || Boolean(inviteToken);
        setRegistrationAvailable(available);
        if (!available) setMode("login");
      })
      .catch(() => {
        if (!active) return;
        // Fail closed in the UI too. A valid invitation still gets a form; the
        // backend remains the authority and validates/claims it on submit.
        setRegistrationAvailable(Boolean(inviteToken));
        if (!inviteToken) setMode("login");
      });
    return () => {
      active = false;
    };
  }, [inviteToken]);

  function switchMode(next: Mode) {
    if (next === "signup" && !registrationAvailable) return;
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
          ...(inviteToken ? { invite_token: inviteToken } : {}),
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
          {registrationAvailable && (
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
          )}
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
            <div>
              <div style={labelStyle}>USERNAME</div>
              <input
                className="input-field"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
              />
            </div>
            <div>
              <div style={labelStyle}>PASSWORD</div>
              <input
                className="input-field"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
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
            <div>
              <div style={labelStyle}>USERNAME</div>
              <input
                className="input-field"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                placeholder="letters, numbers, _ -"
              />
            </div>
            <div>
              <div style={labelStyle}>PASSWORD</div>
              <input
                className="input-field"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                placeholder="min 8 characters"
              />
            </div>
            <div>
              <div style={labelStyle}>CONFIRM PASSWORD</div>
              <input
                className="input-field"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>
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
