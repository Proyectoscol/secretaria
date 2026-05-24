"use client";
import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

const REFRESH_BUFFER_MS = 5 * 60 * 1000; // refresh if < 5 min remaining

// Microsoft platform token routes are Next.js-internal API routes.
// They must NOT be called through /api/proxy (which would forward them to the
// OpenClaw backend instead of the Next.js API handler).
async function msGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "include" });
  if (!res.ok) {
    const err = new Error(res.statusText) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

async function msPost<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: "POST", credentials: "include" });
  if (!res.ok) {
    const err = new Error(res.statusText) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

export function useMicrosoftPlatformToken() {
  const router = useRouter();

  const getValidToken = useCallback(async (): Promise<string | null> => {
    try {
      const data = await msGet<{
        accessToken?: string;
        expiresAt?: string;
        connected: boolean;
      }>("/api/microsoft/platform/token");

      if (!data.connected || !data.accessToken) return null;

      const expiresAt = data.expiresAt ? new Date(data.expiresAt).getTime() : 0;
      const now = Date.now();

      if (expiresAt - now < REFRESH_BUFFER_MS) {
        // Proactively refresh
        const refreshed = await msPost<{
          accessToken: string;
          expiresAt: string;
        }>("/api/microsoft/platform/token/refresh");
        return refreshed.accessToken;
      }

      return data.accessToken;
    } catch (err: unknown) {
      const status = (err as { status?: number }).status;
      if (status === 401 || status === 403) {
        toast.error(
          "Tu conexión con Microsoft ha expirado. Reconecta en Configuración.",
          {
            action: {
              label: "Ir a Configuración",
              onClick: () => router.push("/settings/microsoft"),
            },
          }
        );
        return null;
      }
      return null;
    }
  }, [router]);

  return { getValidToken };
}
