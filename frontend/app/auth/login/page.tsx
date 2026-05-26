"use client";
/**
 * Login page — Microsoft only.
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
    <div className="min-h-screen flex items-center justify-center p-4 overflow-hidden relative bg-background">

      {/* ── Subtle background accents ─────────────────────────────────────── */}
      <div className="absolute inset-0 pointer-events-none" aria-hidden>
        {/* Top-right indigo bloom */}
        <div
          className="absolute -top-80 -right-80 w-[700px] h-[700px] rounded-full blur-[160px]"
          style={{ background: "oklch(0.62 0.22 264)", opacity: 0.08 }}
        />
        {/* Bottom-left violet bloom */}
        <div
          className="absolute -bottom-60 -left-60 w-[600px] h-[600px] rounded-full blur-[140px]"
          style={{ background: "oklch(0.55 0.24 290)", opacity: 0.06 }}
        />
        {/* Dot grid */}
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: "radial-gradient(oklch(0.52 0.22 264 / 0.07) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />
      </div>

      {/* ── Card ─────────────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 28, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-sm relative z-10"
      >
        {/* Logo + wordmark */}
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.1, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-5 bg-primary"
            style={{ boxShadow: "0 8px 32px oklch(0.52 0.22 264 / 0.28)" }}
          >
            <span className="font-display text-2xl font-black text-primary-foreground select-none">K</span>
          </motion.div>

          <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
            KOS
          </h1>
          <p className="text-sm mt-1.5 text-muted-foreground">
            Knowledge Operating System
          </p>
        </div>

        {/* Glass card */}
        <div className="rounded-2xl p-8 bg-card border border-border shadow-lg shadow-foreground/5">
          <div className="text-center mb-6 space-y-1">
            <p className="text-sm font-semibold text-foreground">Iniciar sesión</p>
            <p className="text-xs text-muted-foreground">
              Usa tu cuenta corporativa de Microsoft
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
              text-sm font-medium text-foreground
              bg-secondary border border-border
              hover:bg-secondary/70
              transition-all duration-150
              disabled:opacity-60 disabled:cursor-not-allowed
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
            "
          >
            {loading ? (
              <Loader2 size={16} className="animate-spin shrink-0" />
            ) : (
              <svg
                width="18" height="18" viewBox="0 0 18 18"
                fill="none" aria-hidden="true" className="shrink-0"
              >
                <rect x="0"   y="0"   width="8.5" height="8.5" fill="#F25022" />
                <rect x="9.5" y="0"   width="8.5" height="8.5" fill="#7FBA00" />
                <rect x="0"   y="9.5" width="8.5" height="8.5" fill="#00A4EF" />
                <rect x="9.5" y="9.5" width="8.5" height="8.5" fill="#FFB900" />
              </svg>
            )}
            <span>{loading ? "Redirigiendo…" : "Continuar con Microsoft"}</span>
          </button>

          {/* Divider */}
          <div className="flex items-center gap-3 my-5">
            <div className="flex-1 h-px bg-border" />
            <span className="text-[11px] uppercase tracking-widest text-muted-foreground">o</span>
            <div className="flex-1 h-px bg-border" />
          </div>

          {/* Admin link */}
          <a
            href="/auth/register"
            className="
              w-full flex items-center justify-center
              h-10 px-5 rounded-xl
              text-xs font-medium text-primary
              border border-primary/30 bg-primary/5
              hover:bg-primary/10
              transition-all duration-150
            "
          >
            Configuración inicial · administrador
          </a>

          {/* Inline error */}
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -4, height: 0 }}
              animate={{ opacity: 1, y: 0, height: "auto" }}
              className="mt-4 overflow-hidden"
            >
              <p
                className="text-xs text-center px-3 py-2.5 rounded-lg bg-destructive/10 border border-destructive/25 text-destructive"
                role="alert"
              >
                {error}
              </p>
            </motion.div>
          )}
        </div>

        {/* Footer */}
        <p className="text-center text-[11px] mt-5 text-muted-foreground">
          © {new Date().getFullYear()} Proyectos Col · KOS v1
        </p>
      </motion.div>
    </div>
  );
}
