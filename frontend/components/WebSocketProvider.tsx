"use client";
import { useEffect } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  useWebSocket(); // connects on mount, cleans up on unmount
  return <>{children}</>;
}
