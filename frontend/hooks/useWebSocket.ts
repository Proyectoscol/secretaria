"use client";
import { useEffect, useRef, useCallback } from "react";
import { io, Socket } from "socket.io-client";
import { useSession } from "next-auth/react";
import { useChatStore } from "@/stores/chat";
import { toast } from "sonner";
import type { UploadJob } from "@/types/document";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

type WsEventMap = {
  "document:processing_started": { jobId: string; filename: string };
  "document:processing_done": { jobId: string; filename: string; documentId: string };
  "document:processing_failed": { jobId: string; filename: string; error: string };
  "librarian:searching": { source: string };
  "librarian:found": Record<string, never>;
};

export function useWebSocket() {
  const { data: session, status } = useSession();
  const socketRef = useRef<Socket | null>(null);
  const { setLibrarianStatus, updateMessage, activeSessionId } = useChatStore();
  const reconnectAttempts = useRef(0);

  const connect = useCallback(() => {
    if (!session?.user) return;
    const user = session.user as Record<string, string>;

    const socket = io(WS_URL, {
      auth: {
        userId: user.id,
        tenantId: user.tenantId,
      },
      reconnectionDelay: Math.min(1000 * 2 ** reconnectAttempts.current, 30_000),
      reconnectionAttempts: 20,
      transports: ["websocket"],
    });

    socket.on("connect", () => {
      reconnectAttempts.current = 0;
    });

    socket.on("disconnect", () => {
      reconnectAttempts.current += 1;
    });

    // ── Document events ────────────────────────────────────────────────────────
    socket.on("document:processing_started", ({ filename }: { filename: string }) => {
      toast.loading(`📄 Procesando ${filename}…`, { id: `doc-${filename}` });
    });

    socket.on("document:processing_done", ({ filename, documentId }: { filename: string; documentId: string }) => {
      toast.success(`✓ ${filename} procesado y disponible en tu biblioteca`, {
        id: `doc-${filename}`,
        duration: 5000,
      });
    });

    socket.on("document:processing_failed", ({ filename, error }: { filename: string; error: string }) => {
      toast.error(`⚠ Error procesando ${filename}: ${error}`, {
        id: `doc-${filename}`,
        duration: 8000,
      });
    });

    // ── Librarian status ───────────────────────────────────────────────────────
    socket.on("librarian:searching", ({ source }: { source: string }) => {
      const statusMap: Record<string, "searching_local" | "searching_onedrive" | "querying_db"> = {
        local_semantic: "searching_local",
        local_fulltext: "searching_local",
        onedrive_index: "searching_onedrive",
        onedrive_graph: "searching_onedrive",
        mcp_database: "querying_db",
      };
      setLibrarianStatus(statusMap[source] ?? "searching_local");
    });

    socket.on("librarian:found", () => {
      setLibrarianStatus("idle");
    });

    socketRef.current = socket;
  }, [session, setLibrarianStatus]);

  useEffect(() => {
    if (status === "authenticated") {
      connect();
    }
    return () => {
      socketRef.current?.disconnect();
    };
  }, [status, connect]);

  return { socket: socketRef.current };
}
