"use client";
import Link from "next/link";
import { motion } from "framer-motion";
import { FileText, FileSpreadsheet, Image, MoreVertical, RotateCcw, Trash2, CheckCircle, Clock, AlertCircle, Loader2 } from "lucide-react";
import { cn, formatDate } from "@/lib/utils";
import type { KosDocument } from "@/types/document";

const TYPE_ICONS: Record<string, React.ElementType> = {
  pdf: FileText,
  docx: FileText,
  pptx: FileText,
  xlsx: FileSpreadsheet,
  image: Image,
};

const STATUS_CONFIG = {
  done: { label: "Procesado", color: "text-green-500 bg-green-500/10", Icon: CheckCircle },
  processing: { label: "Procesando", color: "text-amber-500 bg-amber-500/10", Icon: Loader2 },
  pending: { label: "En cola", color: "text-blue-500 bg-blue-500/10", Icon: Clock },
  failed: { label: "Error", color: "text-destructive bg-destructive/10", Icon: AlertCircle },
  quarantined: { label: "Bloqueado", color: "text-destructive bg-destructive/10", Icon: AlertCircle },
};

interface Props {
  doc: KosDocument;
  onReprocess?: (id: string) => void;
  onDelete?: (id: string) => void;
}

export function DocumentCard({ doc, onReprocess, onDelete }: Props) {
  const Icon = TYPE_ICONS[doc.fileType] ?? FileText;
  const status = STATUS_CONFIG[doc.processingStatus] ?? STATUS_CONFIG.pending;
  const StatusIcon = status.Icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="group flex items-center gap-3 px-4 py-3 rounded-xl border border-border bg-card hover:border-primary/30 hover:bg-secondary/40 transition-all"
    >
      {/* File icon */}
      <div className="w-10 h-10 rounded-lg bg-secondary flex items-center justify-center shrink-0">
        <Icon size={18} className="text-muted-foreground" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <Link
          href={`/library/${doc.id}`}
          className="block text-sm font-medium text-foreground hover:text-primary truncate transition-colors"
        >
          {doc.title ?? doc.filenameOriginal}
        </Link>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-muted-foreground">
            {formatDate(doc.createdAt)}
          </span>
          {doc.pageCount && (
            <span className="text-xs text-muted-foreground">
              · {doc.pageCount} pág.
            </span>
          )}
          {doc.chunkCount && (
            <span className="text-xs text-muted-foreground">
              · {doc.chunkCount} fragmentos
            </span>
          )}
        </div>
      </div>

      {/* Status badge */}
      <div className={cn("flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium shrink-0", status.color)}>
        <StatusIcon size={11} className={doc.processingStatus === "processing" ? "animate-spin" : ""} />
        <span className="hidden sm:inline">{status.label}</span>
      </div>

      {/* Actions menu */}
      <div className="relative opacity-0 group-hover:opacity-100 transition-opacity">
        <ActionMenu
          onReprocess={() => onReprocess?.(doc.id)}
          onDelete={() => onDelete?.(doc.id)}
          canReprocess={doc.processingStatus === "failed"}
        />
      </div>
    </motion.div>
  );
}

function ActionMenu({
  onReprocess,
  onDelete,
  canReprocess,
}: {
  onReprocess: () => void;
  onDelete: () => void;
  canReprocess: boolean;
}) {
  return (
    <div className="flex items-center gap-1">
      {canReprocess && (
        <button
          onClick={onReprocess}
          className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors min-h-[36px] min-w-[36px] flex items-center justify-center"
          title="Re-procesar"
        >
          <RotateCcw size={14} />
        </button>
      )}
      <button
        onClick={onDelete}
        className="p-2 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors min-h-[36px] min-w-[36px] flex items-center justify-center"
        title="Eliminar"
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}
