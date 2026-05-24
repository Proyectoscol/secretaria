"use client";
import { motion, AnimatePresence } from "framer-motion";
import { useLibrarianStatus } from "@/hooks/useLibrarianStatus";

export function LibrarianStatusBar() {
  const { label, isActive } = useLibrarianStatus();

  return (
    <AnimatePresence>
      {isActive && label && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          className="px-4 py-2 overflow-hidden"
        >
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            {label}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
