"use client";
/**
 * TokenExpiryBanner — shown in the top of every app page when the user's
 * Microsoft token has expired and needs to be reconnected.
 *
 * Polling:
 *  - Hits /api/proxy/notifications/unread every 60 s.
 *  - Shows an amber banner when a `token_expired` notification is present.
 *  - Hides after the user dismisses (POST /api/proxy/secretary/notifications/dismiss).
 *  - Silent on fetch errors — a transient backend blip must never crash the UI.
 *
 * Security:
 *  - The backend enforces user isolation; this component only renders what
 *    the server already authorised for the logged-in user.
 *  - No user IDs or sensitive data are logged client-side.
 */

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";
import Link from "next/link";

const POLL_INTERVAL_MS = 60_000; // 60 seconds

interface Notification {
  id: string;
  type: string;
  created_at: string | null;
}

async function fetchUnreadNotifications(): Promise<Notification[]> {
  try {
    const res = await fetch("/api/proxy/notifications/unread", {
      // Bypass Next.js client-side fetch cache so every poll is fresh
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.notifications) ? data.notifications : [];
  } catch {
    return [];
  }
}

async function dismissNotification(type: string): Promise<void> {
  await fetch("/api/proxy/secretary/notifications/dismiss", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notification_type: type }),
  });
}

export default function TokenExpiryBanner() {
  const [visible, setVisible] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function checkNotifications() {
    fetchUnreadNotifications().then((notifications) => {
      const hasExpiry = notifications.some((n) => n.type === "token_expired");
      setVisible(hasExpiry);
    });
  }

  useEffect(() => {
    // First check immediately on mount
    checkNotifications();

    // Then poll on interval
    intervalRef.current = setInterval(checkNotifications, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleDismiss() {
    if (dismissing) return;
    setDismissing(true);
    try {
      await dismissNotification("token_expired");
      setVisible(false);
    } catch {
      // Silently ignore — banner will disappear on the next poll cycle
      setVisible(false);
    } finally {
      setDismissing(false);
    }
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key="token-expiry-banner"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          className="overflow-hidden"
        >
          <div
            role="alert"
            aria-live="polite"
            className="
              flex items-center justify-between gap-3
              px-4 py-2.5
              bg-amber-500/15 border-b border-amber-500/30
              text-amber-700 dark:text-amber-300
              text-sm
            "
          >
            {/* Icon + message */}
            <div className="flex items-center gap-2 min-w-0">
              <AlertTriangle
                size={15}
                className="flex-shrink-0 text-amber-500"
                aria-hidden="true"
              />
              <span className="truncate">
                Tu conexión con Microsoft expiró.{" "}
                <Link
                  href="/settings/microsoft"
                  className="
                    font-medium underline underline-offset-2
                    hover:text-amber-900 dark:hover:text-amber-100
                    focus-visible:outline-none focus-visible:ring-2
                    focus-visible:ring-amber-500 focus-visible:ring-offset-1
                    rounded-sm
                  "
                >
                  Reconectar ahora →
                </Link>
              </span>
            </div>

            {/* Dismiss button */}
            <button
              type="button"
              onClick={handleDismiss}
              disabled={dismissing}
              aria-label="Cerrar aviso de token expirado"
              className="
                flex-shrink-0 p-1 rounded-md
                text-amber-600 dark:text-amber-400
                hover:bg-amber-500/20
                transition-colors duration-150
                disabled:opacity-50 disabled:cursor-not-allowed
                focus-visible:outline-none focus-visible:ring-2
                focus-visible:ring-amber-500
              "
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
