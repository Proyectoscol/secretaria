"use client";
import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { BookOpen, Plus } from "lucide-react";
import { useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";
import { DocumentCard } from "@/components/library/DocumentCard";
import { UploadZone } from "@/components/library/UploadZone";
import api from "@/lib/api";
import type { KosDocument, FileType, DocumentStatus } from "@/types/document";

type FilterType = "all" | FileType;
type FilterStatus = "all" | DocumentStatus;

const TYPE_FILTERS: { key: FilterType; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "pdf", label: "PDF" },
  { key: "docx", label: "Word" },
  { key: "xlsx", label: "Excel" },
  { key: "pptx", label: "PowerPoint" },
  { key: "image", label: "Imagen" },
];

const STATUS_FILTERS: { key: FilterStatus; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "done", label: "Procesados" },
  { key: "processing", label: "Procesando" },
  { key: "failed", label: "Con error" },
];

export default function LibraryPage() {
  const { data: session } = useSession();
  const [docs, setDocs] = useState<KosDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState<FilterType>("all");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [showUpload, setShowUpload] = useState(false);

  const user = session?.user as Record<string, string> | undefined;

  const fetchDocs = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await api.get<{ documents: KosDocument[] }>("/library/documents");
      setDocs(res.data.documents ?? []);
    } catch {
      /* will show empty state */
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const filtered = docs.filter((d) => {
    if (typeFilter !== "all" && d.fileType !== typeFilter) return false;
    if (statusFilter !== "all" && d.processingStatus !== statusFilter) return false;
    return true;
  });

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/library/documents/${id}`);
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch {}
  };

  const handleReprocess = async (id: string) => {
    try {
      await api.post(`/library/documents/${id}/reprocess`);
      fetchDocs();
    } catch {}
  };

  return (
    <div className="flex flex-col h-full pt-14 md:pt-0 overflow-hidden">
      {/* Header */}
      <div className="px-4 md:px-6 py-4 border-b border-border shrink-0">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <BookOpen size={20} className="text-primary" />
            <h1 className="font-display text-lg font-semibold text-foreground">
              Biblioteca
            </h1>
            <span className="text-xs text-muted-foreground bg-secondary px-2 py-0.5 rounded-full">
              {docs.length}
            </span>
          </div>
          <Button
            size="sm"
            onClick={() => setShowUpload((v) => !v)}
            className="gap-1.5 h-9"
          >
            <Plus size={15} />
            <span className="hidden sm:inline">Subir</span>
          </Button>
        </div>

        {/* Upload zone (collapsible) */}
        {showUpload && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-4"
          >
            <UploadZone onJobCreated={() => { setShowUpload(false); fetchDocs(); }} />
          </motion.div>
        )}

        {/* Filters */}
        <div className="flex gap-3 mt-4 overflow-x-auto pb-1 scrollbar-none">
          {/* Type filters */}
          <div className="flex gap-1.5 shrink-0">
            {TYPE_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setTypeFilter(f.key)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors whitespace-nowrap ${
                  typeFilter === f.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary text-muted-foreground hover:text-foreground"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="w-px bg-border shrink-0" />
          {/* Status filters */}
          <div className="flex gap-1.5 shrink-0">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setStatusFilter(f.key)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors whitespace-nowrap ${
                  statusFilter === f.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary text-muted-foreground hover:text-foreground"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Document list */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-2 scrollbar-thin">
        {loading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 rounded-xl skeleton" />
          ))
        ) : filtered.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center py-16">
              <BookOpen size={36} className="text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">
                {docs.length === 0
                  ? "No hay documentos. Sube tu primer archivo."
                  : "No hay documentos con esos filtros."}
              </p>
            </div>
          </div>
        ) : (
          filtered.map((doc) => (
            <DocumentCard
              key={doc.id}
              doc={doc}
              onDelete={handleDelete}
              onReprocess={handleReprocess}
            />
          ))
        )}
      </div>
    </div>
  );
}
