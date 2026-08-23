import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { api, apiFetch, setAccessToken, setOnAuthExpired } from "@/lib/api";

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  created_at: string;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  signup: (name: string, email: string, password: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  // Wire the wrapper's "refresh failed" escape hatch to this context, so any
  // authenticated call anywhere in the app can trigger a clean logout.
  useEffect(() => {
    setOnAuthExpired(() => {
      setUser(null);
      setAccessToken(null);
      navigate("/login", { replace: true });
    });
    return () => setOnAuthExpired(null);
  }, [navigate]);

  // On mount: no access token exists yet (it's only ever kept in memory), so
  // this always 401s first — which makes apiFetch attempt exactly the silent
  // refresh this app needs to answer "am I still logged in?" from the
  // httpOnly cookie alone. silentAuthCheck suppresses the redirect-to-login
  // that a *real* session expiry would trigger, since "not logged in yet" is
  // the normal, expected outcome for a first-time visitor.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await apiFetch<AuthUser>("/auth/me", { method: "GET", silentAuthCheck: true });
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function signup(name: string, email: string, password: string): Promise<void> {
    const data = await api.post<TokenResponse>(
      "/auth/signup",
      { name, email, password },
      { skipAuthRetry: true },
    );
    setAccessToken(data.access_token);
    setUser(data.user);
  }

  async function login(email: string, password: string): Promise<void> {
    const data = await api.post<TokenResponse>(
      "/auth/login",
      { email, password },
      { skipAuthRetry: true },
    );
    setAccessToken(data.access_token);
    setUser(data.user);
  }

  async function logout(): Promise<void> {
    try {
      await api.post("/auth/logout", undefined, { skipAuthRetry: true });
    } catch {
      // best-effort — clear local state regardless of whether the network call succeeded
    } finally {
      setAccessToken(null);
      setUser(null);
      navigate("/login", { replace: true });
    }
  }

  const value = useMemo<AuthContextValue>(
    () => ({ user, isLoading, isAuthenticated: user !== null, signup, login, logout }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [user, isLoading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
