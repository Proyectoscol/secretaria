"use client";
/**
 * Login page — Microsoft only.
 *
 * Credential flow (/auth/register) still exists for the initial admin setup
 * but is not surfaced here. Day-to-day access is exclusively via Microsoft.
 *
 * Popup → redirect fallback:
 *  1. signIn({ redirect: false }) opens a popup on desktop.
 *  2. If the browser blocks the popup (common on mobile), fall back to
 *     full-page redirect — works on every device.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";

export default function LoginPage() {
  const router  = useRouter();
  const [loading, setLoading] = useState(false);
  const [error,   setError  ] = useState("");

  async function handleMicrosoftLogin() {
    setLoading(true);
    setError("");

    // ── Attempt popup (desktop) ────────────────────────────────────────────
    const result = await signIn("microsoft-entra-id", {
      redirect: false,
      callbackUrl: "/chat",
    });

    // ── Popup blocked → fall back to full redirect (mobile / strict browsers)
    if (!result || (!result.url && !result.error)) {
      await signIn("microsoft-entra-id", { callbackUrl: "/chat" });
      return;
    }

    if (result.error) {
      setError(
        result.error === "AccessDenied" ||
        result.error.toLowerCase().includes("domain")
          ? "Tu cuenta no pertenece a una organización autorizada."
          : "No se pudo iniciar sesión. Intenta de nuevo."
      );
      setLoading(false);
      return;
    }

    if (result.url) {
      router.push(result.url);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-sm"
      >
        {/* Wordmark */}
        <div className="text-center mb-12">
          <span className="font-display text-3xl font-bold tracking-tight text-foreground">
            OpenClaw <span className="text-primary">KOS</span>
          </span>
          <p className="text-muted-foreground text-sm mt-2">
            Knowledge Operating System
          </p>
        </div>

        {/* Card */}
        <div className="glass rounded-2xl p-8 shadow-2xl flex flex-col items-center gap-6">
          <div className="text-center space-y-1">
            <h1 className="font-display text-lg font-semibold text-foreground">
              Iniciar sesión
            </h1>
            <p className="text-sm text-muted-foreground">
              Usa tu cuenta corporativa Microsoft
            </p>
          </div>

          {/* Microsoft button */}
          <button
            type="button"
            onClick={handleMicrosoftLogin}
            disabled={loading}
            className="
              w-full flex items-center justify-center gap-3
              h-11 px-5 rounded-xl
              border border-border bg-secondary hover:bg-secondary/70
              text-sm font-medium text-foreground
              transition-colors duration-150
              disabled:opacity-60 disabled:cursor-not-allowed
              focus-visible:outline-none focus-visible:ring-2
              focus-visible:ring-primary focus-visible:ring-offset-2
            "
          >
            {loading ? (
              <Loader2 size={16} className="animate-spin flex-shrink-0" />
            ) : (
              <svg
                width="18" height="18" viewBox="0 0 18 18"
                fill="none" aria-hidden="true" className="flex-shrink-0"
              >
                <rect x="0"   y="0"   width="8.5" height="8.5" fill="#F25022" />
                <rect x="9.5" y="0"   width="8.5" height="8.5" fill="#7FBA00" />
                <rect x="0"   y="9.5" width="8.5" height="8.5" fill="#00A4EF" />
                <rect x="9.5" y="9.5" width="8.5" height="8.5" fill="#FFB900" />
              </svg>
            )}
            <span>{loading ? "Redirigiendo…" : "Continuar con Microsoft"}</span>
          </button>

          {/* Inline error — never a toast */}
          {error && (
            <motion.p
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-sm text-red-500 text-center w-full"
              role="alert"
            >
              {error}
            </motion.p>
          )}
        </div>

        {/* Admin setup footnote */}
        <p className="text-center text-xs text-muted-foreground mt-6">
          ¿Primera vez?{" "}
          <a href="/auth/register" className="text-primary hover:underline underline-offset-2">
            Configuración inicial del administrador
          </a>
        </p>
      </motion.div>
    </div>
  );
}
