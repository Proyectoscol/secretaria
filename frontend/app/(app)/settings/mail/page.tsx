"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Mail, Shield, Clock, Bell, Plus, Trash2, Loader2,
  CheckCircle2, XCircle, AlertCircle, Toggle, ToggleLeft,
  ToggleRight, ChevronDown, ChevronUp, Save
} from "lucide-react";
import { useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface MailAccount {
  id: string;
  email_address: string;
  display_name: string;
  is_active: boolean;
  created_at: string | null;
}

interface AuthDomain {
  id: string;
  domain: string;
  description: string | null;
  is_active: boolean;
}

interface ReportSchedule {
  report_type: "daily_summary" | "weekly_metrics" | "monthly_analysis";
  is_active: boolean;
  hour_utc: number;
  minute_utc: number;
  recipients: string[];
  last_sent_at: string | null;
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl border border-zinc-200 overflow-hidden"
    >
      <div className="px-5 py-4 border-b border-zinc-100 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center text-amber-600">
          {icon}
        </div>
        <div>
          <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
          <p className="text-xs text-zinc-400">{description}</p>
        </div>
      </div>
      <div className="p-5">{children}</div>
    </motion.div>
  );
}

// ─── Accounts section ─────────────────────────────────────────────────────────

function AccountsSection() {
  const [accounts, setAccounts] = useState<MailAccount[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<{ accounts: MailAccount[] }>("/librarian/secretary/accounts")
      .then((res) => setAccounts(res.data.accounts ?? []))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Section
      title="Buzones del Secretario"
      description="Cuentas de correo gestionadas por el Secretario IA"
      icon={<Mail className="w-4 h-4" />}
    >
      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="w-5 h-5 text-amber-500 animate-spin" />
        </div>
      ) : accounts.length === 0 ? (
        <p className="text-sm text-zinc-400 text-center py-4">
          No hay buzones configurados.
        </p>
      ) : (
        <ul className="space-y-2">
          {accounts.map((acc) => (
            <li
              key={acc.id}
              className="flex items-center gap-3 px-3 py-2.5 bg-zinc-50 rounded-lg"
            >
              <div
                className={cn(
                  "w-2 h-2 rounded-full flex-shrink-0",
                  acc.is_active ? "bg-green-500" : "bg-zinc-300",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-zinc-900 truncate">
                  {acc.email_address}
                </p>
                <p className="text-xs text-zinc-400 truncate">{acc.display_name}</p>
              </div>
              <Badge
                variant="outline"
                className={cn(
                  "text-xs",
                  acc.is_active
                    ? "text-green-700 border-green-200"
                    : "text-zinc-400",
                )}
              >
                {acc.is_active ? "Activo" : "Inactivo"}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ─── Whitelist section ────────────────────────────────────────────────────────

function WhitelistSection() {
  const [domains, setDomains] = useState<AuthDomain[]>([]);
  const [loading, setLoading] = useState(false);
  const [newDomain, setNewDomain] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    // Fetch whitelist via a GET that returns domains from the DB
    api
      .get<{ accounts: AuthDomain[] }>("/librarian/secretary/whitelist")
      .then((res) => setDomains(res.data.accounts ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const handleAdd = async () => {
    if (!newDomain.trim()) return;
    setAdding(true);
    try {
      await api.post("/librarian/secretary/whitelist", {
        domain: newDomain.trim().toLowerCase(),
        description: newDesc.trim() || undefined,
      });
      setNewDomain("");
      setNewDesc("");
      reload();
    } catch {
      /* show nothing */
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (domain: string) => {
    setRemoving(domain);
    try {
      await api.delete(`/librarian/secretary/whitelist/${encodeURIComponent(domain)}`);
      reload();
    } finally {
      setRemoving(null);
    }
  };

  return (
    <Section
      title="Dominios autorizados"
      description="Solo se procesan correos provenientes de estos dominios"
      icon={<Shield className="w-4 h-4" />}
    >
      {/* Add form */}
      <div className="flex gap-2 mb-4">
        <Input
          placeholder="dominio.com"
          value={newDomain}
          onChange={(e) => setNewDomain(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          className="h-8 text-sm"
        />
        <Input
          placeholder="Descripción (opcional)"
          value={newDesc}
          onChange={(e) => setNewDesc(e.target.value)}
          className="h-8 text-sm hidden sm:block"
        />
        <Button
          size="sm"
          onClick={handleAdd}
          disabled={adding || !newDomain.trim()}
          className="bg-amber-500 hover:bg-amber-600 text-white gap-1"
        >
          {adding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          Agregar
        </Button>
      </div>

      {/* Domain list */}
      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="w-5 h-5 text-amber-500 animate-spin" />
        </div>
      ) : domains.length === 0 ? (
        <div className="text-center py-4">
          <AlertCircle className="w-6 h-6 text-amber-400 mx-auto mb-2" />
          <p className="text-sm text-zinc-500 font-medium">Sin dominios autorizados</p>
          <p className="text-xs text-zinc-400 mt-1">
            No se procesará ningún correo hasta agregar al menos un dominio.
          </p>
        </div>
      ) : (
        <ul className="space-y-1.5">
          {domains.map((d) => (
            <li
              key={d.id || d.domain}
              className="flex items-center gap-3 px-3 py-2 bg-zinc-50 rounded-lg group"
            >
              <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <span className="text-sm font-mono text-zinc-900">{d.domain}</span>
                {d.description && (
                  <span className="text-xs text-zinc-400 ml-2">{d.description}</span>
                )}
              </div>
              <button
                onClick={() => handleRemove(d.domain)}
                disabled={removing === d.domain}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-zinc-400 hover:text-red-500 p-1 rounded"
              >
                {removing === d.domain ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Trash2 className="w-3.5 h-3.5" />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ─── Report schedules section ─────────────────────────────────────────────────

const REPORT_TYPES = [
  { key: "daily_summary", label: "Resumen Diario", desc: "Enviado todos los días a la hora configurada" },
  { key: "weekly_metrics", label: "Métricas Semanales", desc: "Enviado los lunes a la hora configurada" },
  { key: "monthly_analysis", label: "Análisis Mensual", desc: "Enviado el 1° de cada mes" },
] as const;

function SchedulesSection() {
  const [schedules, setSchedules] = useState<ReportSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, Partial<ReportSchedule>>>({});

  useEffect(() => {
    api
      .get<{ schedules: ReportSchedule[] }>("/librarian/secretary/schedules")
      .then((res) => {
        const s = res.data.schedules ?? [];
        setSchedules(s);
        const initial: Record<string, Partial<ReportSchedule>> = {};
        for (const sched of s) {
          initial[sched.report_type] = { ...sched };
        }
        setForm(initial);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async (reportType: string) => {
    const data = form[reportType];
    if (!data) return;
    setSaving(reportType);
    try {
      await api.put(`/librarian/secretary/schedules/${reportType}`, {
        is_active: data.is_active ?? false,
        hour_utc: data.hour_utc ?? 7,
        minute_utc: data.minute_utc ?? 0,
        recipients: data.recipients ?? [],
      });
    } finally {
      setSaving(null);
    }
  };

  const updateForm = (type: string, patch: Partial<ReportSchedule>) => {
    setForm((prev) => ({ ...prev, [type]: { ...(prev[type] ?? {}), ...patch } }));
  };

  return (
    <Section
      title="Reportes programados"
      description="Configura qué reportes envía el Secretario y a quién"
      icon={<Clock className="w-4 h-4" />}
    >
      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="w-5 h-5 text-amber-500 animate-spin" />
        </div>
      ) : (
        <div className="space-y-4">
          {REPORT_TYPES.map(({ key, label, desc }) => {
            const s = form[key] ?? {};
            const isActive = s.is_active ?? false;

            return (
              <div key={key} className="border border-zinc-100 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <p className="text-sm font-medium text-zinc-900">{label}</p>
                    <p className="text-xs text-zinc-400">{desc}</p>
                  </div>
                  <button
                    onClick={() => updateForm(key, { is_active: !isActive })}
                    className={cn(
                      "relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
                      isActive ? "bg-amber-500" : "bg-zinc-200",
                    )}
                  >
                    <span
                      className={cn(
                        "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform",
                        isActive ? "translate-x-4" : "translate-x-0",
                      )}
                    />
                  </button>
                </div>

                {isActive && (
                  <div className="space-y-2">
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <Label className="text-xs text-zinc-500 mb-1 block">Hora UTC</Label>
                        <Input
                          type="number"
                          min={0}
                          max={23}
                          value={s.hour_utc ?? 7}
                          onChange={(e) => updateForm(key, { hour_utc: Number(e.target.value) })}
                          className="h-7 text-xs"
                        />
                      </div>
                      <div className="flex-1">
                        <Label className="text-xs text-zinc-500 mb-1 block">Minuto</Label>
                        <Input
                          type="number"
                          min={0}
                          max={59}
                          value={s.minute_utc ?? 0}
                          onChange={(e) => updateForm(key, { minute_utc: Number(e.target.value) })}
                          className="h-7 text-xs"
                        />
                      </div>
                    </div>
                    <div>
                      <Label className="text-xs text-zinc-500 mb-1 block">
                        Destinatarios (uno por línea)
                      </Label>
                      <textarea
                        value={(s.recipients ?? []).join("\n")}
                        onChange={(e) =>
                          updateForm(key, {
                            recipients: e.target.value
                              .split("\n")
                              .map((r) => r.trim())
                              .filter(Boolean),
                          })
                        }
                        rows={3}
                        style={{ fontSize: "16px" }}
                        className="w-full rounded border border-zinc-200 px-2 py-1.5 text-xs text-zinc-800 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
                      />
                    </div>
                    <Button
                      size="sm"
                      onClick={() => handleSave(key)}
                      disabled={saving === key}
                      className="bg-amber-500 hover:bg-amber-600 text-white gap-1.5 h-7 text-xs"
                    >
                      {saving === key ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Save className="w-3 h-3" />
                      )}
                      Guardar
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function MailSettingsPage() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-900">Configuración de Correo</h1>
        <p className="text-sm text-zinc-400 mt-1">
          Gestiona buzones, dominios autorizados y reportes del Secretario IA.
        </p>
      </div>

      <AccountsSection />
      <WhitelistSection />
      <SchedulesSection />
    </div>
  );
}
