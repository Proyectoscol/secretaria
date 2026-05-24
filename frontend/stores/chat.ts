import { create } from "zustand";
import type { Message, ChatSession, AttachedFile, LibrarianStatus } from "@/types/chat";

interface ChatStore {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: Record<string, Message[]>;
  librarianStatus: LibrarianStatus;
  attachedFile: AttachedFile | null;
  isStreaming: boolean;

  setSessions: (sessions: ChatSession[]) => void;
  setActiveSession: (id: string | null) => void;
  addMessage: (sessionId: string, message: Message) => void;
  updateMessage: (sessionId: string, messageId: string, patch: Partial<Message>) => void;
  setLibrarianStatus: (status: LibrarianStatus) => void;
  setAttachedFile: (file: AttachedFile | null) => void;
  setStreaming: (v: boolean) => void;
  clearMessages: (sessionId: string) => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  sessions: [],
  activeSessionId: null,
  messages: {},
  librarianStatus: "idle",
  attachedFile: null,
  isStreaming: false,

  setSessions: (sessions) => set({ sessions }),
  setActiveSession: (id) => set({ activeSessionId: id }),

  addMessage: (sessionId, message) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [sessionId]: [...(s.messages[sessionId] ?? []), message],
      },
    })),

  updateMessage: (sessionId, messageId, patch) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [sessionId]: (s.messages[sessionId] ?? []).map((m) =>
          m.id === messageId ? { ...m, ...patch } : m
        ),
      },
    })),

  setLibrarianStatus: (librarianStatus) => set({ librarianStatus }),
  setAttachedFile: (attachedFile) => set({ attachedFile }),
  setStreaming: (isStreaming) => set({ isStreaming }),
  clearMessages: (sessionId) =>
    set((s) => ({ messages: { ...s.messages, [sessionId]: [] } })),
}));
