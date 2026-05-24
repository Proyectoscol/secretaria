"use client";
import { useChatStore } from "@/stores/chat";
import type { LibrarianStatus } from "@/types/chat";

const STATUS_LABELS: Record<LibrarianStatus, string | null> = {
  idle: null,
  searching_local: "🔍 Buscando en biblioteca…",
  searching_onedrive: "📁 Revisando OneDrive…",
  querying_db: "🗄 Consultando base de datos…",
};

export function useLibrarianStatus() {
  const status = useChatStore((s) => s.librarianStatus);
  return {
    status,
    label: STATUS_LABELS[status],
    isActive: status !== "idle",
  };
}
