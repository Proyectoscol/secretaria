"use client";
import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, Loader2 } from "lucide-react";
import { useDocumentUpload } from "@/hooks/useDocumentUpload";
import { cn } from "@/lib/utils";

const ACCEPT = {
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
};

export function UploadZone({ onJobCreated }: { onJobCreated?: (jobId: string) => void }) {
  const { upload, uploading } = useDocumentUpload();
  const [isDragOver, setIsDragOver] = useState(false);

  const onDrop = useCallback(
    async (accepted: File[]) => {
      for (const file of accepted) {
        const job = await upload(file);
        if (job) onJobCreated?.(job.jobId);
      }
    },
    [upload, onJobCreated]
  );

  const { getRootProps, getInputProps } = useDropzone({
    onDrop,
    accept: ACCEPT,
    maxSize: 100 * 1024 * 1024,
    onDragEnter: () => setIsDragOver(true),
    onDragLeave: () => setIsDragOver(false),
    onDropAccepted: () => setIsDragOver(false),
    onDropRejected: () => setIsDragOver(false),
  });

  return (
    <div
      {...getRootProps()}
      className={cn(
        "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200",
        isDragOver
          ? "border-primary bg-primary/5 amber-glow"
          : "border-border hover:border-primary/50 hover:bg-secondary/30"
      )}
    >
      <input {...getInputProps()} />
      <AnimatePresence mode="wait">
        {uploading ? (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center gap-3"
          >
            <Loader2 size={28} className="text-primary animate-spin" />
            <p className="text-sm text-muted-foreground">Subiendo documento…</p>
          </motion.div>
        ) : (
          <motion.div
            key="idle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center gap-3"
          >
            <div className={cn(
              "w-12 h-12 rounded-xl flex items-center justify-center transition-colors",
              isDragOver ? "bg-primary/20" : "bg-secondary"
            )}>
              <Upload size={22} className={isDragOver ? "text-primary" : "text-muted-foreground"} />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {isDragOver ? "Suelta para subir" : "Arrastra documentos aquí"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                PDF, DOCX, XLSX, PPTX, JPG, PNG — máx. 100 MB
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
