"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import Link from "next/link";
import { Eye, EyeOff, UserPlus, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { registerSchema, type RegisterInput, emailDomainRefinement } from "@/lib/validators";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function RegisterPage() {
  const router = useRouter();
  const [showPwd, setShowPwd] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<RegisterInput>({
    resolver: zodResolver(registerSchema),
    mode: "onChange",
  });

  const email = watch("email") ?? "";
  const domainValid = email.includes("@") && emailDomainRefinement(email);

  const onSubmit = async (data: RegisterInput) => {
    setLoading(true);
    setServerError(null);
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fullName: data.fullName,
          email: data.email,
          password: data.password,
        }),
      });
      const body = await res.json();
      if (!res.ok) {
        setServerError(body.error ?? "Error al registrar");
        return;
      }
      router.push("/auth/login?registered=1");
    } catch {
      setServerError("Error de conexión");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-md"
      >
        <div className="text-center mb-10">
          <span className="font-display text-3xl font-bold tracking-tight text-foreground">
            OpenClaw <span className="text-primary">KOS</span>
          </span>
          <p className="text-muted-foreground text-sm mt-2">Crear cuenta corporativa</p>
        </div>

        <div className="glass rounded-2xl p-8 shadow-2xl">
          <h1 className="font-display text-xl font-semibold mb-6 text-foreground">
            Registro
          </h1>

          {serverError && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="mb-4 px-4 py-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm"
            >
              {serverError}
            </motion.div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="fullName">Nombre completo</Label>
              <Input
                id="fullName"
                placeholder="Ana García"
                autoComplete="name"
                {...register("fullName")}
                className={errors.fullName ? "border-destructive" : ""}
              />
              {errors.fullName && (
                <p className="text-xs text-destructive">{errors.fullName.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="email">Correo corporativo</Label>
              <div className="relative">
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  placeholder="tu@empresa.com"
                  {...register("email")}
                  className={`pr-9 ${errors.email ? "border-destructive" : ""}`}
                />
                {email.includes("@") && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2">
                    {domainValid ? (
                      <CheckCircle2 size={15} className="text-green-500" />
                    ) : (
                      <XCircle size={15} className="text-destructive" />
                    )}
                  </span>
                )}
              </div>
              {errors.email && (
                <p className="text-xs text-destructive">{errors.email.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Contraseña</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPwd ? "text" : "password"}
                  placeholder="Mín. 8 caracteres, 1 mayúscula, 1 número"
                  autoComplete="new-password"
                  {...register("password")}
                  className={`pr-10 ${errors.password ? "border-destructive" : ""}`}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  tabIndex={-1}
                >
                  {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {errors.password && (
                <p className="text-xs text-destructive">{errors.password.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="confirmPassword">Confirmar contraseña</Label>
              <div className="relative">
                <Input
                  id="confirmPassword"
                  type={showConfirm ? "text" : "password"}
                  placeholder="Repetir contraseña"
                  autoComplete="new-password"
                  {...register("confirmPassword")}
                  className={`pr-10 ${errors.confirmPassword ? "border-destructive" : ""}`}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  tabIndex={-1}
                >
                  {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {errors.confirmPassword && (
                <p className="text-xs text-destructive">{errors.confirmPassword.message}</p>
              )}
            </div>

            <Button type="submit" className="w-full h-11 font-semibold" disabled={loading}>
              {loading ? (
                <Loader2 size={16} className="animate-spin mr-2" />
              ) : (
                <UserPlus size={16} className="mr-2" />
              )}
              {loading ? "Creando cuenta…" : "Crear cuenta"}
            </Button>
          </form>

          <p className="text-center text-sm text-muted-foreground mt-6">
            ¿Ya tienes cuenta?{" "}
            <Link href="/auth/login" className="text-primary font-medium hover:underline">
              Iniciar sesión
            </Link>
          </p>
        </div>
      </motion.div>
    </div>
  );
}
