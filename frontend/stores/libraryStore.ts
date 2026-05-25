import { create } from "zustand";
import type { Document, DocumentFilter } from "@/types/document";

interface LibraryStore {
  documents: Document[];
  totalCount: number;
  filters: DocumentFilter;
  isUploading: boolean;
  uploadProgress: number;

  setDocuments: (docs: Document[], total?: number) => void;
  prependDocument: (doc: Document) => void;
  updateDocument: (id: string, patch: Partial<Document>) => void;
  setFilter: (key: keyof DocumentFilter, value: string | null) => void;
  resetFilters: () => void;
  setUploading: (uploading: boolean) => void;
  setUploadProgress: (pct: number) => void;
}

const DEFAULT_FILTERS: DocumentFilter = {
  type: null,
  status: null,
  search: null,
};

export const useLibraryStore = create<LibraryStore>((set) => ({
  documents: [],
  totalCount: 0,
  filters: { ...DEFAULT_FILTERS },
  isUploading: false,
  uploadProgress: 0,

  setDocuments: (documents, total) =>
    set({ documents, totalCount: total ?? documents.length }),

  prependDocument: (doc) =>
    set((s) => ({
      documents: [doc, ...s.documents],
      totalCount: s.totalCount + 1,
    })),

  updateDocument: (id, patch) =>
    set((s) => ({
      documents: s.documents.map((d) => (d.id === id ? { ...d, ...patch } : d)),
    })),

  setFilter: (key, value) =>
    set((s) => ({ filters: { ...s.filters, [key]: value } })),

  resetFilters: () => set({ filters: { ...DEFAULT_FILTERS } }),

  setUploading: (isUploading) => set({ isUploading }),

  setUploadProgress: (uploadProgress) => set({ uploadProgress }),
}));
