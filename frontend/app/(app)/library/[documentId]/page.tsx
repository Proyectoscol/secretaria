"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, MessageSquarePlus, FileText, Image, Calendar, User, Hash } from "lucide-react";
import { Button } from "@/components/ui/button";
import api from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { DocumentDetail } from "@/types/document";

export default function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const router = useRouter();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<DocumentDetail>(`/library/documents/${documentId}`)
      .then((r) => setDoc(r.data))
      .catch(() => setDoc(null))
      .finally(() => setLoading(false));
  }, [documentId]);

  const openInChat = () => {
    router.push(`/chat/new?doc=${documentId}`);
  };

  if (loading) {
    return (
      <div className="flex flex-col h-full pt-14 md:pt-0 p-6 space-y-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className={`h-${i === 0 ? 8 : 4} rounded-lg skeleton`} />
        ))}
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground text-sm">Documento no encontrado.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full pt-14 md:pt-0 overflow-hidden">
      {/* Header */}
      <div className="px-4 md:px-6 py-4 border-b border-border shrink-0 flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="font-display text-base font-semibold text-foreground truncate">
            {doc.title ?? doc.filenameOriginal}
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {doc.filenameOriginal} · {formatDate(doc.createdAt)}
          </p>
        </div>
        <Button size="sm" onClick={openInChat} className="gap-1.5 shrink-0">
          <MessageSquarePlus size={14} />
          <span className="hidden sm:inline">Preguntar</span>
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <div className="max-w-3xl mx-auto px-4 md:px-6 py-6">
          {/* Metadata */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6"
          >
            {[
              { Icon: Calendar, label: "Procesado", value: formatDate(doc.createdAt) },
              { Icon: FileText, label: "Páginas", value: doc.pageCount ?? "—" },
              { Icon: Hash, label: "Fragmentos", value: doc.chunkCount ?? "—" },
              { Icon: User, label: "Idioma", value: doc.languageDetected ?? "—" },
            ].map(({ Icon, label, value }) => (
              <div
                key={label}
                className="flex flex-col gap-1 px-3 py-2.5 rounded-lg bg-secondary/50 border border-border"
              >
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Icon size={12} />
                  {label}
                </div>
                <p className="text-sm font-medium text-foreground">{String(value)}</p>
              </div>
            ))}
          </motion.div>

          {/* Authors / keywords */}
          {(doc.authors?.length || doc.keywords?.length) && (
            <div className="flex flex-wrap gap-2 mb-6">
              {doc.authors?.map((a) => (
                <span key={a} className="px-2 py-1 rounded-full text-xs bg-secondary text-muted-foreground">
                  {a}
                </span>
              ))}
              {doc.keywords?.map((k) => (
                <span key={k} className="px-2 py-1 rounded-full text-xs bg-primary/10 text-primary border border-primary/20">
                  {k}
                </span>
              ))}
            </div>
          )}

          {/* Sections TOC */}
          {doc.sections?.length > 0 && (
            <div className="mb-6">
              <h2 className="font-display text-sm font-semibold text-foreground mb-3">
                Contenido
              </h2>
              <div className="space-y-1">
                {doc.sections.map((s, i) => (
                  <div
                    key={i}
                    className="text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                    style={{ paddingLeft: `${(s.level - 1) * 16}px` }}
                  >
                    {s.title}
                    {s.page && <span className="text-xs ml-2 text-muted-foreground/60">p.{s.page}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Figures */}
          {doc.figures?.length > 0 && (
            <div className="mb-6">
              <h2 className="font-display text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                <Image size={14} /> Figuras extraídas
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {doc.figures.map((f) => (
                  <div key={f.id} className="rounded-lg border border-border overflow-hidden">
                    {/* Image preview — served via proxy */}
                    <div className="aspect-video bg-secondary flex items-center justify-center">
                      <Image size={24} className="text-muted-foreground/30" />
                    </div>
                    {f.caption && (
                      <p className="px-2 py-1.5 text-xs text-muted-foreground line-clamp-2">
                        {f.caption}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Canonical markdown */}
          <div className="prose-chat">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {/* Canonical content loaded on demand */}
              {`*Vista previa del documento disponible tras procesamiento completo.*`}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}
