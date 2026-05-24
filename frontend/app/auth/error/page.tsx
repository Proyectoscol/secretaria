"use client";
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
  OAuthAccountNotLinked: {
    title: "Cuenta ya registrada",
    body: "Este correo ya tiene una cuenta local. Inicia sesión con tu contraseña y luego vincula tu cuenta Microsoft desde Configuración.",
  },
  default: {
    title: "Error de autenticación",
    body: "Ocurrió un error al iniciar sesión. Por favor intenta nuevamente.",
  },
};

export default function AuthErrorPage() {
  const params = useSearchParams();
  const reason = params.get("reason") ?? params.get("error") ?? "default";
  const { title, body } = MESSAGES[reason] ?? MESSAGES.default;

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.35 }}
        className="w-full max-w-md"
      >
        <div className="glass rounded-2xl p-10 shadow-2xl text-center">
          <div className="w-16 h-16 rounded-full bg-destructive/15 flex items-center justify-center mx-auto mb-6">
            <ShieldAlert size={32} className="text-destructive" />
          </div>
          <h1 className="font-display text-xl font-semibold mb-3 text-foreground">{title}</h1>
          <p className="text-muted-foreground text-sm leading-relaxed mb-8">{body}</p>
          <Button asChild variant="outline" className="gap-2">
            <Link href="/auth/login">
              <ArrowLeft size={14} />
              Volver al inicio de sesión
            </Link>
          </Button>
        </div>
      </motion.div>
    </div>
  );
}
