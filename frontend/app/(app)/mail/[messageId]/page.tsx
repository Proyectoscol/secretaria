"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  ArrowLeft, Mail, User, Clock, Tag, Paperclip,
  ExternalLink, Loader2, AlertCircle, Reply, Archive
} from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ThreadMessage {
  id: string;
  from_address: string;
  from_name: string | null;
  subject: string;
  body: string | null;
  snippet: string | null;
  received_at: string | null;
  direction: "inbound" | "outbound";
  ai_classification: string | null;
  ai_priority: string | null;
  ai_action_taken: string | null;
}

interface Thread {
  id: string;
  subject: string;
  participants: Array<{ email: string; name?: string }>;
  first_message_at: string | null;
  last_message_at: string | null;
  message_count: number;
  status: string;
  ai_summary: string | null;
}

interface ThreadDetail {
  thread: Thread;
  messages: ThreadMessage[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("es-CO", {
    day: "numeric", month: "long", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

const CLASSIFICATION_LABELS: Record<string, string> = {
  report_request: "Solicitud de reporte",
  query: "Consulta",
  alert_acknowledgment: "Confirmación de alerta",
  reply: "Respuesta",
  informational: "Informativo",
};

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg, index }: { msg: ThreadMessage; index: number }) {
  const isOutbound = msg.direction === "outbound";
  const [showHtml, setShowHtml] = useState(true);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className={cn("mb-6", isOutbound && "pl-8")}
    >
      {/* Sender row */}
      <div className="flex items-center gap-2 mb-2">
        <div
          className={cn(
            "w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0",
            isOutbound
              ? "bg-amber-100 text-amber-700"
              : "bg-zinc-100 text-zinc-600",
          )}
        >
          {isOutbound ? "IA" : (msg.from_name?.[0] ?? msg.from_address[0]).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-zinc-900">
            {isOutbound ? "Secretaria IA" : (msg.from_name || msg.from_address)}
          </span>
          {!isOutbound && (
            <span className="text-xs text-zinc-400 ml-2">{msg.from_address}</span>
          )}
        </div>
        <span className="text-xs text-zinc-400 flex-shrink-0">{formatDate(msg.received_at)}</span>
      </div>

      {/* Message body */}
      <div
        className={cn(
          "rounded-lg border text-sm",
          isOutbound
            ? "bg-amber-50 border-amber-100"
            : "bg-white border-zinc-200",
        )}
      >
        {/* Body content */}
        <div className="p-4">
          {msg.body ? (
            showHtml ? (
              <div
                className="prose prose-sm max-w-none text-zinc-700"
                /* Safe: body_sanitized is sanitized server-side before storage */
                dangerouslySetInnerHTML={{ __html: msg.body }}
              />
            ) : (
              <pre className="text-xs text-zinc-600 whitespace-pre-wrap font-mono">
                {msg.body}
              </pre>
            )
          ) : (
            <p className="text-zinc-400 italic text-xs">{msg.snippet || "(sin contenido)"}</p>
          )}
        </div>

        {/* AI metadata footer */}
        {(msg.ai_classification || msg.ai_action_taken) && (
          <div className="px-4 py-2 border-t border-zinc-100 bg-zinc-50 rounded-b-lg flex flex-wrap gap-2 items-center">
            {msg.ai_classification && (
              <Badge variant="outline" className="text-xs h-5 font-normal">
                🤖 {CLASSIFICATION_LABELS[msg.ai_classification] ?? msg.ai_classification}
              </Badge>
            )}
            {msg.ai_action_taken && (
              <span className="text-xs text-zinc-400">
                Acción: {msg.ai_action_taken.replace(/_/g, " ")}
              </span>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function MailDetailPage() {
  const params = useParams();
  const router = useRouter();
  const threadId = params.messageId as string;

  const [detail, setDetail] = useState<ThreadDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!threadId) return;
    setLoading(true);
    api
      .get<ThreadDetail>(`/librarian/secretary/threads/${threadId}`)
      .then((res) => setDetail(res.data))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [threadId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 text-amber-500 animate-spin" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-sm text-zinc-500">No se pudo cargar el hilo de correo.</p>
        <Button variant="outline" size="sm" onClick={() => router.back()}>
          Volver
        </Button>
      </div>
    );
  }

  const { thread, messages } = detail;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-zinc-100 bg-white sticky top-0 z-10">
        <div className="flex items-center gap-3 mb-1">
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 -ml-1"
            onClick={() => router.back()}
          >
            <ArrowLeft className="w-4 h-4" />
            Bandeja
          </Button>
        </div>
        <h1 className="text-base font-semibold text-zinc-900 truncate">{thread.subject}</h1>
        <div className="flex items-center gap-3 mt-1 flex-wrap">
          <span className="text-xs text-zinc-400 flex items-center gap-1">
            <User className="w-3 h-3" />
            {thread.participants?.map((p) => p.email).join(", ")}
          </span>
          <span className="text-xs text-zinc-400 flex items-center gap-1">
            <Mail className="w-3 h-3" />
            {thread.message_count} mensaje{thread.message_count !== 1 ? "s" : ""}
          </span>
        </div>

        {/* AI summary */}
        {thread.ai_summary && (
          <div className="mt-2 px-3 py-2 bg-amber-50 border border-amber-100 rounded-md">
            <p className="text-xs text-amber-800">
              <span className="font-medium">Resumen IA:</span> {thread.ai_summary}
            </p>
          </div>
        )}
      </div>

      {/* Thread messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.map((msg, i) => (
          <MessageBubble key={msg.id} msg={msg} index={i} />
        ))}
      </div>

      {/* Action bar */}
      <div className="px-6 py-3 border-t border-zinc-100 flex gap-2">
        <Link href={`/mail/compose?reply_to=${threadId}`} className="flex-1">
          <Button variant="outline" size="sm" className="w-full gap-1.5">
            <Reply className="w-3.5 h-3.5" />
            Responder
          </Button>
        </Link>
      </div>
    </div>
  );
}
