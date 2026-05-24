"use client";

/**
 * /settings/health — System health dashboard.
 *
 * Admin-only page. The server-side API endpoint verifies role='admin'
 * before returning any infrastructure data.
 *
 * Polls every 30 seconds. Each service shows: name, status, latency,
 * last check timestamp, and an optional detail string.
 */

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity, Database, Mail, Cpu, HardDrive, RefreshCw,
  CheckCircle2, XCircle, AlertCircle, Loader2, Clock,
  Server, Shield, Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type ServiceStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

interface ServiceHealth {
  name: string;
  status: ServiceStatus;
  latency_ms: number | null;
  checked_at: string | null;
  detail: string | null;
}

interface HealthData {
  overall: ServiceStatus;
  checked_at: string;
  services: ServiceHealth[];
  version: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 30_000;

const SERVICE_ICONS: Record<string, React.ReactNode> = {
  postgres:  <Database className="w-4 h-4" />,
  redis:     <Zap className="w-4 h-4" />,
  clamav:    <Shield className="w-4 h-4" />,
  librarian: <Server className="w-4 h-4" />,
  celery:    <Cpu className="w-4 h-4" />,
  smtp:      <Mail className="w-4 h-4" />,
  imap:      <Mail className="w-4 h-4" />,
  langfuse:  <Activity className="w-4 h-4" />,
  storage:   <HardDrive className="w-4 h-4" />,
};

// ── Status helpers ────────────────────────────────────────────────────────────

function StatusIcon({ status }: { status: ServiceStatus }) {
  switch (status) {
    case "healthy":   return <CheckCircle2 className="w-4 h-4 text-green-500" />;
    case "degraded":  return <AlertCircle  className="w-4 h-4 text-amber-500" />;
    case "unhealthy": return <XCircle      className="w-4 h-4 text-red-500"   />;
    default:          return <AlertCircle  className="w-4 h-4 text-zinc-400"  />;
  }
}

function StatusBadge({ status }: { status: ServiceStatus }) {
  const styles: Record<ServiceStatus, string> = {
    healthy:   "bg-green-50 text-green-700 border-green-200",
    degraded:  "bg-amber-50 text-amber-700 border-amber-200",
    unhealthy: "bg-red-50   text-red-700   border-red-200",
    unknown:   "bg-zinc-50  text-zinc-500  border-zinc-200",
  };
  const labels: Record<ServiceStatus, string> = {
    healthy: "Saludable", degraded: "Degradado",
    unhealthy: "No disponible", unknown: "Desconocido",
  };
  return (
    <Badge variant="outline" className={cn("text-xs font-medium", styles[status])}>
      {labels[status]}
    </Badge>
  );
}

function OverallBanner({ status }: { status: ServiceStatus }) {
  const config: Record<ServiceStatus, { bg: string; text: string; icon: React.ReactNode; label: string }> = {
    healthy: {
      bg: "bg-green-50 border-green-200",
      text: "text-green-800",
      icon: <CheckCircle2 className="w-5 h-5 text-green-600" />,
      label: "Todos los sistemas operando correctamente",
    },
    degraded: {
      bg: "bg-amber-50 border-amber-200",
      text: "text-amber-800",
      icon: <AlertCircle className="w-5 h-5 text-amber-600" />,
      label: "Algunos servicios degradados — verifique detalles",
    },
    unhealthy: {
      bg: "bg-red-50 border-red-200",
      text: "text-red-800",
      icon: <XCircle className="w-5 h-5 text-red-600" />,
      label: "Uno o más servicios no disponibles",
    },
    unknown: {
      bg: "bg-zinc-50 border-zinc-200",
      text: "text-zinc-700",
      icon: <AlertCircle className="w-5 h-5 text-zinc-400" />,
      label: "Estado del sistema desconocido",
    },
  };
  const c = config[status];
  return (
    <div className={cn("flex items-center gap-3 rounded-xl border px-4 py-3", c.bg)}>
      {c.icon}
      <span className={cn("text-sm font-medium", c.text)}>{c.label}</span>
    </div>
  );
}

// ── Service card ──────────────────────────────────────────────────────────────

function ServiceCard({ svc }: { svc: ServiceHealth }) {
  const key = svc.name.toLowerCase().replace(/[^a-z]/g, "");
  const icon = SERVICE_ICONS[key] ?? <Server className="w-4 h-4" />;

  const formattedAt = svc.checked_at
    ? new Date(svc.checked_at).toLocaleTimeString("es-CO", {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      })
    : "—";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-start gap-3 bg-white rounded-xl border border-zinc-200 px-4 py-3"
    >
      {/* Icon */}
      <div className="w-8 h-8 rounded-lg bg-zinc-50 border border-zinc-100 flex items-center justify-center text-zinc-500 flex-shrink-0 mt-0.5">
        {icon}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <StatusIcon status={svc.status} />
            <span className="text-sm font-semibold text-zinc-900 capitalize">{svc.name}</span>
          </div>
          <StatusBadge status={svc.status} />
        </div>

        <div className="mt-1 flex items-center gap-4 text-xs text-zinc-400">
          {svc.latency_ms !== null && (
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {svc.latency_ms}ms
            </span>
          )}
          <span>Última verificación: {formattedAt}</span>
        </div>

        {svc.detail && (
          <p className="mt-1 text-xs text-zinc-500 truncate">{svc.detail}</p>
        )}
      </div>
    </motion.div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function HealthPage() {
  const [data, setData]       = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [lastPoll, setLastPoll] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchHealth = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const res = await api.get<HealthData>("/librarian/secretary/health");
      setData(res.data);
      setError(null);
      setLastPoll(new Date());
    } catch (err: unknown) {
      if (err instanceof Error) {
        if (err.message.includes("403") || err.message.includes("Forbidden")) {
          setError("Acceso denegado. Esta página es solo para administradores.");
        } else {
          setError(`Error al cargar el estado del sistema: ${err.message}`);
        }
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Initial load
  useEffect(() => { fetchHealth(); }, [fetchHealth]);

  // Poll every 30s
  useEffect(() => {
    const id = setInterval(() => fetchHealth(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchHealth]);

  // ── Access denied ─────────────────────────────────────────────────────────
  if (error?.includes("denegado")) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 flex flex-col items-center gap-4">
        <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center">
          <Shield className="w-6 h-6 text-red-500" />
        </div>
        <h2 className="text-lg font-semibold text-zinc-900">Acceso restringido</h2>
        <p className="text-sm text-zinc-500 text-center">
          El tablero de salud solo está disponible para administradores.
        </p>
      </div>
    );
  }

  // ── Loading ───────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="w-6 h-6 text-amber-500 animate-spin" />
      </div>
    );
  }

  // ── Error ─────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      </div>
    );
  }

  // ── Dashboard ─────────────────────────────────────────────────────────────

  const grouped = {
    critical: data?.services.filter(s =>
      ["postgres", "redis", "librarian", "celery"].includes(s.name.toLowerCase())
    ) ?? [],
    mail: data?.services.filter(s =>
      ["smtp", "imap", "clamav"].includes(s.name.toLowerCase())
    ) ?? [],
    optional: data?.services.filter(s =>
      !["postgres", "redis", "librarian", "celery", "smtp", "imap", "clamav"].includes(s.name.toLowerCase())
    ) ?? [],
  };

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900">Estado del Sistema</h1>
          <p className="text-sm text-zinc-400 mt-0.5">
            {lastPoll
              ? `Última actualización: ${lastPoll.toLocaleTimeString("es-CO")}`
              : "Cargando…"}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => fetchHealth(true)}
          disabled={refreshing}
          className="gap-1.5"
        >
          {refreshing
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <RefreshCw className="w-3.5 h-3.5" />}
          Actualizar
        </Button>
      </div>

      {/* Overall banner */}
      {data && <OverallBanner status={data.overall} />}

      {/* Version info */}
      {data?.version && (
        <p className="text-xs text-zinc-400 text-right">
          KOS v{data.version}
        </p>
      )}

      {/* Critical services */}
      {grouped.critical.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Servicios críticos
          </h2>
          <div className="space-y-2">
            {grouped.critical.map(svc => (
              <ServiceCard key={svc.name} svc={svc} />
            ))}
          </div>
        </div>
      )}

      {/* Mail services */}
      {grouped.mail.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Servicios de correo
          </h2>
          <div className="space-y-2">
            {grouped.mail.map(svc => (
              <ServiceCard key={svc.name} svc={svc} />
            ))}
          </div>
        </div>
      )}

      {/* Other services */}
      {grouped.optional.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Servicios adicionales
          </h2>
          <div className="space-y-2">
            {grouped.optional.map(svc => (
              <ServiceCard key={svc.name} svc={svc} />
            ))}
          </div>
        </div>
      )}

      {/* No services */}
      {(!data || data.services.length === 0) && (
        <div className="text-center py-12 text-sm text-zinc-400">
          No se encontraron servicios para monitorear.
        </div>
      )}

      {/* Auto-refresh note */}
      <p className="text-xs text-zinc-400 text-center pt-2">
        Se actualiza automáticamente cada 30 segundos.
      </p>
    </div>
  );
}
