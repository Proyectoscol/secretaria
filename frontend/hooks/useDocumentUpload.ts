"use client";
import { useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import type { UploadJob } from "@/types/document";

const MAX_SIZE = 100 * 1024 * 1024; // 100 MB
const ALLOWED_TYPES: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
  "image/jpeg": "image",
  "image/png": "image",
};

export function useDocumentUpload() {
  const { data: session } = useSession();
  const [job, setJob] = useState<UploadJob | null>(null);
  const [uploading, setUploading] = useState(false);

  const upload = useCallback(
    async (file: File): Promise<UploadJob | null> => {
      // Client-side validation before hitting the server
      if (file.size > MAX_SIZE) {
        toast.error(`Archivo demasiado grande (máx. 100 MB): ${file.name}`);
        return null;
      }
      if (!ALLOWED_TYPES[file.type]) {
        toast.error(`Tipo de archivo no permitido: ${file.type}`);
        return null;
      }

      setUploading(true);
      const toastId = toast.loading(`📄 Subiendo ${file.name}…`);

      try {
        const form = new FormData();
        form.append("file", file);
        form.append("file_type", ALLOWED_TYPES[file.type]);

        // Append session fields as form fields — the proxy also injects them as
        // headers (X-Tenant-ID / X-User-ID), but form fields are a belt-and-
        // suspenders fallback for the librarian upload endpoint.
        const user = session?.user as Record<string, string> | undefined;
        if (user?.id) form.append("user_id", user.id);
        if (user?.tenantId) form.append("tenant_id", user.tenantId);

        // /api/proxy/upload → proxy routes "upload" prefix → LIBRARIAN_API_URL/internal/upload
        const res = await fetch("/api/proxy/upload", {
          method: "POST",
          credentials: "include",
          body: form,
          // Do NOT set Content-Type — browser sets multipart boundary automatically
        });

        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          throw new Error(detail?.detail ?? `Upload failed: ${res.status}`);
        }

        const data: { jobId: string } = await res.json();

        const uploadJob: UploadJob = {
          jobId: data.jobId,
          status: "queued",
          filename: file.name,
        };
        setJob(uploadJob);
        toast.dismiss(toastId);
        toast.loading(`📄 Procesando ${file.name}…`, { id: `job-${data.jobId}` });
        return uploadJob;
      } catch (err) {
        toast.dismiss(toastId);
        toast.error(`Error subiendo ${file.name}: ${(err as Error).message ?? ""}`);
        return null;
      } finally {
        setUploading(false);
      }
    },
    [session]
  );

  return { upload, job, uploading };
}
