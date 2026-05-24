"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Mail, Inbox, RefreshCw, Loader2, Search, Filter,
  FileText, AlertCircle, CheckCircle2, Clock, ChevronRight,
  Tag, Paperclip
} from "lucide-react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface MailThread {
  id: string;
  subject: string;
  participants: Array<{ email: string; name?: string }>;
  first_message_at: string | null;
  last_message_at: string | null;
  message_count: number;
  status: "active" | "archived" | "processed";
  ai_summary: string | null;
}

interface MailMessage {
  id: string;
  thread_id: string | null;
  from_address: string;
  from_name: string | null;
  subject: string;
  snippet: string | null;
  received_at: string | null;
  ai_classification: string | null;
  ai_priority: "high" | "medium" | "low" | null;
  processing_status: string;
  thread_message_count: number | null;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const CLASSIFICATION_LABELS: Record<string, string> = {
  report_request: "Reporte",
  query: "Consulta",
  alert_acknowledgment: "Confirmación",
  reply: "Respuesta",
  informational: "Info",
};

const PRIORITY_COLORS: Record<string, string> = {
  high: "bg-red-100 text-red-700 border-red-200",
  medium: "bg-amber-100 text-amber-700 border-amber-200",
  low: "bg-zinc-100 text-zinc-600 border-zinc-200",
};

const STATUS_ICON: Record<string, React.ReactNode> = {
  processed: <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />,
  processing: <Clock className="w-3.5 h-3.5 text-amber-500" />,
  pending: <Clock className="w-3.5 h-3.5 text-zinc-400" />,
  failed: <AlertCircle className="w-3.5 h-3.5 text-red-500" />,
  rejected: <AlertCircle className="w-3.5 h-3.5 text-zinc-400" />,
};

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "Ahora";
  if (diffMins < 60) return `hace ${diffMins}m`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `hace ${diffHours}h`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `hace ${diffDays}d`;
  return date.toLocaleDateString("es-CO", { day: "numeric", month: "short" });
}

// ─── Filter tabs ─────────────────────────────────────────────────────────────

type FilterType = "all" | "report_request" | "query" | "reply" | "informational";

const FILTERS: { key: FilterType; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "report_request", label: "Reportes" },
  { key: "query", label: "Consultas" },
  { key: "reply", label: "Respuestas" },
  { key: "informational", label: "Informativos" },
];

// ─── Thread row component ─────────────────────────────────────────────────────

function ThreadRow({ msg, index }: { msg: MailMessage; index: number }) {
  const href = msg.thread_id ? `/mail/${msg.thread_id}` : `/mail/${msg.id}`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
    >
      <Link href={href}>
        <div
          className={cn(
            "flex items-start gap-3 px-4 py-3.5 border-b border-zinc-100 hover:bg-zinc-50 cursor-pointer transition-colors group",
            msg.processing_status === "pending" && "bg-amber-50/30",
          )}
        >
          {/* Status icon */}
          <div className="mt-1 flex-shrink-0">
            {STATUS_ICON[msg.processing_status] ?? <Mail className="w-3.5 h-3.5 text-zinc-400" />}
          </div>

          {/* Main content */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-sm font-medium text-zinc-900 truncate">
                {msg.from_name || msg.from_address}
              </span>
              {msg.thread_message_count && msg.thread_message_count > 1 && (
                <span className="text-xs text-zinc-400 bg-zinc-100 rounded-full px-1.5 py-px">
                  {msg.thread_message_count}
                </span>
              )}
              <span className="ml-auto text-xs text-zinc-400 flex-shrink-0">
                {formatRelativeTime(msg.received_at)}
              </span>
            </div>

            <p className="text-sm text-zinc-700 truncate mb-1">{msg.subject}</p>

            <div className="flex items-center gap-2">
              {msg.snippet && (
                <p className="text-xs text-zinc-400 truncate flex-1">{msg.snippet}</p>
              )}
              <div className="flex items-center gap-1 flex-shrink-0">
                {msg.ai_classification && (
                  <Badge
                    variant="outline"
                    className="text-xs h-4 px-1.5 py-0 font-normal"
                  >
                    {CLASSIFICATION_LABELS[msg.ai_classification] ?? msg.ai_classification}
                  </Badge>
                )}
                {msg.ai_priority && (
                  <Badge
                    variant="outline"
                    className={cn("text-xs h-4 px-1.5 py-0 font-normal border", PRIORITY_COLORS[msg.ai_priority])}
                  >
                    {msg.ai_priority === "high" ? "Alta" : msg.ai_priority === "medium" ? "Media" : "Baja"}
                  </Badge>
                )}
              </div>
            </div>
          </div>

          <ChevronRight className="w-4 h-4 text-zinc-300 group-hover:text-zinc-500 mt-1 flex-shrink-0 transition-colors" />
        </div>
      </Link>
    </motion.div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function MailPage() {
  const { data: session } = useSession();
  const [messages, setMessages] = useState<MailMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterType>("all");

  const fetchMessages = useCallback(async (silent = false) => {
    if (!session) return;
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const res = await api.get<{ messages: MailMessage[] }>("/librarian/secretary/inbox?limit=100");
      setMessages(res.data.messages ?? []);
    } catch {
      /* show empty state */
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [session]);

  useEffect(() => {
    fetchMessages();
    // Auto-refresh every 60s
    const id = setInterval(() => fetchMessages(true), 60_000);
    return () => clearInterval(id);
  }, [fetchMessages]);

  const filtered = messages.filter((m) => {
    if (filter !== "all" && m.ai_classification !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        m.subject.toLowerCase().includes(q) ||
        m.from_address.toLowerCase().includes(q) ||
        (m.snippet ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 pt-6 pb-4 border-b border-zinc-100">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Inbox className="w-5 h-5 text-amber-500" />
            <h1 className="text-xl font-semibold text-zinc-900">Bandeja del Secretario</h1>
            {messages.length > 0 && (
              <span className="text-sm text-zinc-400 font-normal ml-1">
                ({messages.length})
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Link href="/mail/compose">
              <Button variant="outline" size="sm" className="gap-1.5">
                <Mail className="w-3.5 h-3.5" />
                Redactar
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => fetchMessages(true)}
              disabled={refreshing}
              className="gap-1.5"
            >
              <RefreshCw className={cn("w-3.5 h-3.5", refreshing && "animate-spin")} />
              Actualizar
            </Button>
          </div>
        </div>

        {/* Search */}
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
          <Input
            placeholder="Buscar correos…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 text-sm"
          />
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1 overflow-x-auto">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "px-3 py-1 text-xs rounded-full whitespace-nowrap transition-colors",
                filter === f.key
                  ? "bg-amber-500 text-white font-medium"
                  : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-48">
            <Loader2 className="w-6 h-6 text-amber-500 animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-center px-6">
            <Inbox className="w-10 h-10 text-zinc-200 mb-3" />
            <p className="text-sm font-medium text-zinc-500">
              {search || filter !== "all" ? "Sin resultados para este filtro" : "Bandeja vacía"}
            </p>
            <p className="text-xs text-zinc-400 mt-1">
              {search || filter !== "all"
                ? "Prueba otro término de búsqueda o filtro"
                : "Los correos entrantes autorizados aparecerán aquí"}
            </p>
          </div>
        ) : (
          <AnimatePresence>
            {filtered.map((msg, i) => (
              <ThreadRow key={msg.id} msg={msg} index={i} />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
