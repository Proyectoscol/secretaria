/**
 * Axios instance — all calls go through /api/proxy to avoid CORS and
 * to centralise auth headers.  Never call the backend directly from the browser.
 */
import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { getSession, signOut } from "next-auth/react";

const api = axios.create({
  baseURL: "/api/proxy",
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// ── Request: inject session headers ──────────────────────────────────────────
api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  // Session is available client-side via getSession()
  if (typeof window !== "undefined") {
    try {
      const session = await getSession();
      if (session?.user) {
        const u = session.user as Record<string, string>;
        config.headers["X-User-ID"] = u.id;
        config.headers["X-Tenant-ID"] = u.tenantId;
      }
    } catch {
      // Session not available — let the request proceed; server will reject 401
    }
  }
  return config;
});

// ── Response: handle 401 globally ────────────────────────────────────────────
api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      await signOut({ callbackUrl: "/auth/login" });
    }
    return Promise.reject(error);
  }
);

export default api;

// ── Typed helpers ─────────────────────────────────────────────────────────────
export const librarian = {
  query: (body: {
    query: string;
    tenant_id: string;
    user_id: string;
    session_id?: string;
    context_hints?: Record<string, unknown>;
    microsoft_token?: string;
  }) => api.post("/librarian/query", body),

  ingest: (body: {
    file_path: string;
    file_type: string;
    source_type?: string;
    tenant_id: string;
    user_id: string;
    session_id?: string;
  }) => api.post("/librarian/ingest", body),

  jobStatus: (jobId: string) => api.get(`/librarian/status/${jobId}`),
};
