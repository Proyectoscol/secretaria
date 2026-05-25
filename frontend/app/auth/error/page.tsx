"use client";
/**
 * /auth/error — NextAuth authentication error page.
 *
 * useSearchParams() must be inside a <Suspense> boundary; the outer page
 * component provides that boundary and shows a fallback while the params load.
 */
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import Link from "next/link";
import { ShieldAlert, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

const MESSAGES: Record<string, { title: string; body: string }> = {
  domain: {
    title: "Acceso restringido",
    body: "Tu cuenta de correo no está autorizada para acceder a este sistema. Solo se permiten correos corporativos.",
  },
  AccessDenied: {
    title: "Acceso denegado",
    body: "No tienes permiso para acceder a esta aplicación.",
  },
  OAuthAccountNotLinked: {
    title: "Cuenta ya registrada",
    body: "Este correo ya tiene una cuenta local. Inicia sesión con tu contraseña y luego vincula tu cuenta Microsoft desde Configuración.",
  },
  Configuration: {
    title: "Error de configuración",
    body: "Hay un problema con la configuración del proveedor de autenticación.",
  },
  default: {
    title: "Error de autenticación",
    body: "Ocurrió un error al iniciar sesión. Por favor intenta nuevamente.",
  },
};

/** Inner component — reads searchParams; must be inside Suspense */
function AuthErrorContent() {
  const params = useSearchParams();
  const reason = params.get("reason") ?? params.get("error") ?? "default";
  const { title, body } = MESSAGES[reason] ?? MESSAGES.default;

  return (
    <div className="glass rounded-2xl p-10 shadow-2xl text-center">
      <div className="w-16 h-16 rounded-full bg-destructive/15 flex items-center justify-center mx-auto mb-6">
        <ShieldAlert size={32} className="text-destructive" />
      </div>
      <h1 className="font-display text-xl font-semibold mb-3 text-foreground">
        {title}
      </h1>
      <p className="text-muted-foreground text-sm leading-relaxed mb-8">{body}</p>
      <Button asChild variant="outline" className="gap-2">
        <Link href="/auth/login">
          <ArrowLeft size={14} />
          Volver al inicio de sesión
        </Link>
      </Button>
    </div>
  );
}

/** Fallback shown while Suspense resolves */
function AuthErrorFallback() {
  return (
    <div className="glass rounded-2xl p-10 shadow-2xl text-center">
      <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mx-auto mb-6 animate-pulse" />
      <div className="h-5 w-48 bg-muted rounded mx-auto mb-3 animate-pulse" />
      <div className="h-4 w-64 bg-muted rounded mx-auto animate-pulse" />
    </div>
  );
}

export default function AuthErrorPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.35 }}
        className="w-full max-w-md"
      >
        <Suspense fallback={<AuthErrorFallback />}>
          <AuthErrorContent />
        </Suspense>
      </motion.div>
    </div>
  );
}
