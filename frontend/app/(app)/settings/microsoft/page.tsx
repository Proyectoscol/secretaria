"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  FolderOpen, Mail, Calendar, CheckCircle2, XCircle,
  Clock, RefreshCw, Loader2, AlertTriangle
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { MicrosoftPlatformStatus, MicrosoftFeature } from "@/types/microsoft";

// Microsoft platform routes are Next.js-internal API routes — call them directly,
// NOT through /api/proxy (which forwards to the OpenClaw backend).
const msApi = {
  get: async <T>(path: string): Promise<{ data: T }> => {
    const res = await fetch(path, { credentials: "include" });
    if (!res.ok) throw Object.assign(new Error(res.statusText), { response: { status: res.status } });
    return { data: await res.json() as T };
  },
  post: async <T>(path: string): Promise<{ data: T }> => {
    const res = await fetch(path, { method: "POST", credentials: "include" });
    if (!res.ok) throw Object.assign(new Error(res.statusText), { response: { status: res.status } });
    return { data: await res.json() as T };
  },
  delete: async (path: string): Promise<void> => {
    const res = await fetch(path, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw Object.assign(new Error(res.statusText), { response: { status: res.status } });
  },
};

const FEATURES: MicrosoftFeature[] = [
  {
    key: "onedrive",
    label: "Archivos de OneDrive",
    description: "Busca y procesa archivos directamente desde tu OneDrive",
    scope: "Files.Read.All",
    envFlag: "NEXT_PUBLIC_FEATURE_ONEDRIVE",
    icon: "📁",
    enabled: process.env.NEXT_PUBLIC_FEATURE_ONEDRIVE === "true",
    comingSoon: false,
  },
  {
    key: "mail",
    label: "Correo electrónico",
    description: "Indexa correos relevantes como fuente de conocimiento",
    scope: "Mail.Read",
    envFlag: "NEXT_PUBLIC_FEATURE_MAIL",
    icon: "📧",
    enabled: process.env.NEXT_PUBLIC_FEATURE_MAIL === "true",
    comingSoon: true,
  },
  {
    key: "calendar",
    label: "Calendario",
    description: "Accede a reuniones y eventos como contexto",
    scope: "Calendars.Read",
    envFlag: "NEXT_PUBLIC_FEATURE_CALENDAR",
    icon: "📅",
    enabled: process.env.NEXT_PUBLIC_FEATURE_CALENDAR === "true",
    comingSoon: true,
  },
];

export default function MicrosoftSettingsPage() {
  const [status, setStatus] = useState<MicrosoftPlatformStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  useEffect(() => {
    msApi.get<MicrosoftPlatformStatus>("/api/microsoft/platform/status")
      .then((r) => setStatus(r.data))
      .catch(() => setStatus({ connected: false, scopesGranted: [] }))
      .finally(() => setLoading(false));
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const res = await msApi.post<{ authUrl: string }>("/api/microsoft/platform/connect");
      window.location.href = res.data.authUrl;
    } catch {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await msApi.delete("/api/microsoft/platform/disconnect");
      setStatus({ connected: false, scopesGranted: [] });
    } catch {}
    setDisconnecting(false);
  };

  if (loading) {
    return (
      <div className="flex-1 p-6 space-y-4 pt-14 md:pt-6">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="h-40 rounded-xl skeleton" />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full pt-14 md:pt-0 overflow-hidden">
      <div className="px-4 md:px-6 py-4 border-b border-border shrink-0">
        <h1 className="font-display text-lg font-semibold text-foreground">
          Integraciones Microsoft
        </h1>
        <p className="text-xs text-muted-foreground mt-1">
          Conecta tus servicios de Microsoft para ampliar la base de conocimiento.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-6 space-y-6 scrollbar-thin max-w-2xl">
        {/* Platform permissions card */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-border bg-card overflow-hidden"
        >
          {/* Card header */}
          <div className="px-5 py-4 border-b border-border flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-foreground">
                Permisos de plataforma
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Acceso a tus recursos de Microsoft 365
              </p>
            </div>
            {status?.connected ? (
              <div className="flex items-center gap-1.5 text-xs font-medium text-green-500">
                <CheckCircle2 size={14} />
                Conectado
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <XCircle size={14} />
                No conectado
              </div>
            )}
          </div>

          {/* Feature list */}
          <div className="px-5 py-4 space-y-3">
            {FEATURES.map((f) => {
              const isGranted = status?.scopesGranted.includes(f.scope);
              return (
                <div key={f.key} className="flex items-start gap-3">
                  <span className="text-base mt-0.5">{f.icon}</span>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground">{f.label}</p>
                      {f.comingSoon && (
                        <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                          Próximamente
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{f.description}</p>
                  </div>
                  <div className="shrink-0 mt-0.5">
                    {f.comingSoon ? (
                      <Clock size={14} className="text-muted-foreground/50" />
                    ) : isGranted ? (
                      <CheckCircle2 size={14} className="text-green-500" />
                    ) : (
                      <div className="w-3.5 h-3.5 rounded-full border-2 border-border" />
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Actions */}
          <div className="px-5 py-4 border-t border-border flex items-center gap-3">
            {status?.connected ? (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleConnect}
                  disabled={connecting}
                  className="gap-1.5"
                >
                  {connecting ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  Actualizar permisos
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleDisconnect}
                  disabled={disconnecting}
                  className="text-destructive hover:text-destructive hover:bg-destructive/10 gap-1.5"
                >
                  {disconnecting ? <Loader2 size={13} className="animate-spin" /> : null}
                  Desconectar
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                onClick={handleConnect}
                disabled={connecting}
                className="gap-2"
              >
                {connecting ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <svg width="14" height="14" viewBox="0 0 18 18" fill="none">
                    <rect width="8.5" height="8.5" fill="#F25022" />
                    <rect x="9.5" width="8.5" height="8.5" fill="#7FBA00" />
                    <rect y="9.5" width="8.5" height="8.5" fill="#00A4EF" />
                    <rect x="9.5" y="9.5" width="8.5" height="8.5" fill="#FFB900" />
                  </svg>
                )}
                {connecting ? "Redirigiendo…" : "Conectar y dar permisos"}
              </Button>
            )}
          </div>
        </motion.div>

        {/* Info note */}
        <div className="flex gap-3 px-4 py-3 rounded-lg bg-secondary/50 border border-border">
          <AlertTriangle size={14} className="text-muted-foreground shrink-0 mt-0.5" />
          <p className="text-xs text-muted-foreground leading-relaxed">
            Los permisos de plataforma son <strong className="text-foreground">independientes</strong> del inicio de sesión.
            Puedes estar autenticado sin tener permisos de plataforma activos.
            Los tokens se almacenan cifrados con AES-256.
          </p>
        </div>
      </div>
    </div>
  );
}
