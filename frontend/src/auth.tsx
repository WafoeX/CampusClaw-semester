/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  type FormEvent,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

const ACCESS_TOKEN_STORAGE_KEY = "campusclaw.access-token";

export type Identity = {
  user_id: string;
  account: string;
  role: "teacher" | "student";
  class_id: string;
};

type LoginResponse = Identity & {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
};

type AuthContextValue = {
  identity: Identity | null;
  loading: boolean;
  error: string | null;
  login: (account: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  authorizationHeader: () => HeadersInit | null;
  handleUnauthenticated: () => void;
  clearError: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function jsonError(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      return String(detail.message);
    }
  }
  return fallback;
}

function storedAccessToken(): string | null {
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function clearStoredAccessToken(): void {
  try {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    // Treat inaccessible storage as already cleared.
  }
}

function storeAccessToken(token: string): boolean {
  try {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
    return true;
  } catch {
    return false;
  }
}

export function safeReturnTarget(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/materials";
  }
  try {
    const parsed = new URL(value, window.location.origin);
    if (parsed.origin !== window.location.origin) return "/materials";
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/materials";
  }
}

export function AuthProvider({ children }: PropsWithChildren) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const clearAuthentication = useCallback(() => {
    clearStoredAccessToken();
    setIdentity(null);
  }, []);

  const authorizationHeader = useCallback((): HeadersInit | null => {
    const token = storedAccessToken();
    if (!token) return null;
    return { Authorization: `Bearer ${token}` };
  }, []);

  const refreshIdentity = useCallback(async () => {
    const headers = authorizationHeader();
    if (!headers) {
      clearAuthentication();
      setLoading(false);
      return;
    }
    try {
      const response = await fetch("/api/auth/me", { headers });
      if (!response.ok) {
        clearAuthentication();
        return;
      }
      setIdentity((await response.json()) as Identity);
    } catch {
      clearAuthentication();
    } finally {
      setLoading(false);
    }
  }, [authorizationHeader, clearAuthentication]);

  useEffect(() => {
    void refreshIdentity();
  }, [refreshIdentity]);

  const login = useCallback(async (account: string, password: string) => {
    setError(null);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ account, password }),
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        setError(jsonError(body, "Login failed"));
        return false;
      }
      const loginResponse = body as LoginResponse;
      if (!storeAccessToken(loginResponse.access_token)) {
        setError("Unable to persist the access token");
        return false;
      }
      setIdentity({
        user_id: loginResponse.user_id,
        account: loginResponse.account,
        role: loginResponse.role,
        class_id: loginResponse.class_id,
      });
      return true;
    } catch {
      setError("Unable to reach the server");
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      const headers = authorizationHeader();
      await fetch("/api/auth/logout", { method: "POST", headers: headers ?? undefined });
    } finally {
      clearAuthentication();
      setError(null);
    }
  }, [authorizationHeader, clearAuthentication]);

  const value = useMemo(
    () => ({
      identity,
      loading,
      error,
      login,
      logout,
      authorizationHeader,
      handleUnauthenticated: clearAuthentication,
      clearError: () => setError(null),
    }),
    [identity, loading, error, login, logout, authorizationHeader, clearAuthentication],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function LoginPage() {
  const { identity, login, error, clearError, loading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const returnTarget = safeReturnTarget(new URLSearchParams(location.search).get("returnTo"));

  useEffect(() => {
    if (identity) navigate(returnTarget, { replace: true });
  }, [identity, navigate, returnTarget]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    clearError();
    const succeeded = await login(account, password);
    setSubmitting(false);
    if (succeeded) navigate(returnTarget, { replace: true });
  }

  if (loading) {
    return (
      <main className="auth-shell" aria-busy="true">
        <p className="status-card" role="status">正在确认登录状态…</p>
      </main>
    );
  }
  return (
    <main className="auth-shell">
      <div className="auth-layout">
        <section className="auth-intro" aria-label="CampusClaw 平台简介">
          <div className="brand-lockup">
            <span className="brand-mark" aria-hidden="true">CC</span>
            <div>
              <p className="brand-name">CAMPUSCLAW</p>
              <p className="brand-caption">CLASS MATERIAL HUB</p>
            </div>
          </div>
          <div className="auth-intro-copy">
            <p className="eyebrow">YOUR CLASS, CONNECTED</p>
            <h1>课程资料，清晰汇聚。</h1>
            <p>进入专属班级空间，安全查看与管理每一份教学资料。</p>
          </div>
          <p className="security-note"><span aria-hidden="true">◆</span> 班级数据隔离 · Token 验证访问</p>
        </section>
        <form className="auth-card" onSubmit={submit} aria-label="登录表单">
          <div className="auth-card-heading">
            <p className="eyebrow">WELCOME BACK</p>
            <h2>Sign in to your class</h2>
            <p className="muted">使用班级账号继续访问课程资料。</p>
          </div>
          <label>
            Account
            <input value={account} onChange={(event) => setAccount(event.target.value)} autoComplete="username" required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? "登录中…" : "登录"}
          </button>
        </form>
      </div>
    </main>
  );
}

export function ProtectedRoute({ children }: PropsWithChildren) {
  const { identity, loading } = useAuth();
  const location = useLocation();
  if (loading) return <main className="page-shell" aria-busy="true"><p className="status-card" role="status">正在加载…</p></main>;
  if (!identity) {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }
  return children;
}

export function MaterialsPlaceholder() {
  const { identity, logout } = useAuth();
  return (
    <main className="page-shell">
      <header className="page-header"><div><p className="eyebrow">CLASS LIBRARY</p><h1>Materials</h1></div><button type="button" onClick={() => void logout()}>退出登录</button></header>
      <p>Signed in as <strong>{identity?.account}</strong>.</p>
    </main>
  );
}
