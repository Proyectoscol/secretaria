import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "@/types/auth";

interface SessionStore {
  user: User | null;
  setUser: (user: User | null) => void;
  microsoftToken: string | null;
  setMicrosoftToken: (token: string | null) => void;
}

export const useSessionStore = create<SessionStore>()(
  persist(
    (set) => ({
      user: null,
      setUser: (user) => set({ user }),
      microsoftToken: null,
      setMicrosoftToken: (microsoftToken) => set({ microsoftToken }),
    }),
    { name: "kos-session", partialize: (s) => ({ user: s.user }) }
  )
);
