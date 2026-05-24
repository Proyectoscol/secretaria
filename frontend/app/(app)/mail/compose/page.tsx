"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, Send, Loader2, X, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

export default function ComposePage() {
  const router = useRouter();
  const params = useSearchParams();
  const replyTo = params.get("reply_to");

  const [to, setTo] = useState("");
  const [toList, setToList] = useState<string[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const addRecipient = () => {
    const addr = to.trim().toLowerCase();
    if (addr && addr.includes("@") && !toList.includes(addr)) {
      setToList((prev) => [...prev, addr]);
      setTo("");
    }
  };

  const handleToKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addRecipient();
    }
  };

  const handleSend = async () => {
    // Add pending recipient
    const finalTo = [...toList];
    const pending = to.trim().toLowerCase();
    if (pending && pending.includes("@") && !finalTo.includes(pending)) {
      finalTo.push(pending);
    }

    if (!finalTo.length) { setError("Agrega al menos un destinatario."); return; }
    if (!subject.trim()) { setError("El asunto es obligatorio."); return; }
    if (!body.trim()) { setError("El cuerpo del mensaje es obligatorio."); return; }

    setError("");
    setSending(true);
    try {
      await api.post("/librarian/secretary/send", {
        to_addresses: finalTo,
        subject: subject.trim(),
        body_html: `<p style="font-family:sans-serif;font-size:14px;line-height:1.6;color:#374151;">${body.replace(/\n/g, "<br>")}</p>`,
        body_text: body,
        trigger_type: "manual",
        ...(replyTo ? { in_reply_to: replyTo } : {}),
      });
      setSent(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error al enviar";
      setError(msg);
    } finally {
      setSending(false);
    }
  };

  if (sent) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center"
        >
          <Send className="w-6 h-6 text-green-600" />
        </motion.div>
        <div className="text-center">
          <p className="text-sm font-medium text-zinc-900">Correo enviado</p>
          <p className="text-xs text-zinc-400 mt-1">El Secretario IA lo procesará en breve.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => router.push("/mail")}>
          Volver a la bandeja
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-zinc-100">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" className="gap-1.5 -ml-1" onClick={() => router.back()}>
            <ArrowLeft className="w-4 h-4" />
            Cancelar
          </Button>
          <h1 className="text-base font-semibold text-zinc-900">Nuevo correo</h1>
        </div>
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
        {/* To */}
        <div>
          <Label className="text-xs font-medium text-zinc-600 mb-1.5 block">Para</Label>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {toList.map((addr) => (
              <span
                key={addr}
                className="flex items-center gap-1 bg-zinc-100 text-zinc-700 text-xs px-2 py-1 rounded-full"
              >
                {addr}
                <button onClick={() => setToList((prev) => prev.filter((a) => a !== addr))}>
                  <X className="w-3 h-3 hover:text-red-500" />
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              type="email"
              placeholder="destinatario@empresa.com"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              onKeyDown={handleToKeyDown}
              onBlur={addRecipient}
              className="h-9 text-sm"
            />
            <Button
              variant="outline"
              size="sm"
              onClick={addRecipient}
              disabled={!to.trim()}
              className="gap-1"
            >
              <Plus className="w-3.5 h-3.5" />
              Agregar
            </Button>
          </div>
          <p className="text-xs text-zinc-400 mt-1">Presiona Enter o coma para agregar.</p>
        </div>

        {/* Subject */}
        <div>
          <Label className="text-xs font-medium text-zinc-600 mb-1.5 block">Asunto</Label>
          <Input
            placeholder="Asunto del correo"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="h-9 text-sm"
          />
        </div>

        {/* Body */}
        <div>
          <Label className="text-xs font-medium text-zinc-600 mb-1.5 block">Mensaje</Label>
          <textarea
            placeholder="Escribe tu mensaje aquí…"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={12}
            style={{ fontSize: "16px" }}
            className="w-full rounded-md border border-zinc-200 bg-white px-3 py-2 text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent resize-y"
          />
        </div>

        {/* Error */}
        {error && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded px-3 py-2">
            {error}
          </p>
        )}
      </div>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-zinc-100 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          Cancelar
        </Button>
        <Button
          onClick={handleSend}
          disabled={sending}
          size="sm"
          className="bg-amber-500 hover:bg-amber-600 text-white gap-1.5"
        >
          {sending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
          {sending ? "Enviando…" : "Enviar"}
        </Button>
      </div>
    </div>
  );
}
