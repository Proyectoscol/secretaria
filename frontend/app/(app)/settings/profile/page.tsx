"use client";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { motion } from "framer-motion";
import { Loader2, Save, User } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import api from "@/lib/api";

const profileSchema = z.object({
  fullName: z.string().min(2, "Mínimo 2 caracteres"),
});

const pwdSchema = z
  .object({
    currentPassword: z.string().min(1, "Requerido"),
    newPassword: z
      .string()
      .min(8, "Mínimo 8 caracteres")
      .regex(/[A-Z]/, "Requiere mayúscula")
      .regex(/[0-9]/, "Requiere número"),
    confirmPassword: z.string(),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: "Las contraseñas no coinciden",
    path: ["confirmPassword"],
  });

type ProfileInput = z.infer<typeof profileSchema>;
type PwdInput = z.infer<typeof pwdSchema>;

export default function ProfilePage() {
  const { data: session } = useSession();
  const user = session?.user as Record<string, string> | undefined;
  const isLocalUser = (user as { source?: string })?.source !== "microsoft";

  const initials = user?.name?.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase() ?? "??";

  const {
    register: regProfile,
    handleSubmit: handleProfile,
    formState: { errors: errProfile, isDirty },
  } = useForm<ProfileInput>({
    resolver: zodResolver(profileSchema),
    defaultValues: { fullName: user?.name ?? "" },
  });

  const {
    register: regPwd,
    handleSubmit: handlePwd,
    formState: { errors: errPwd },
    reset: resetPwd,
  } = useForm<PwdInput>({ resolver: zodResolver(pwdSchema) });

  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPwd, setSavingPwd] = useState(false);

  const onSaveProfile = async (data: ProfileInput) => {
    setSavingProfile(true);
    try {
      await api.patch("/auth/profile", { fullName: data.fullName });
      toast.success("Perfil actualizado");
    } catch {
      toast.error("Error al actualizar perfil");
    }
    setSavingProfile(false);
  };

  const onChangePwd = async (data: PwdInput) => {
    setSavingPwd(true);
    try {
      await api.post("/auth/change-password", {
        currentPassword: data.currentPassword,
        newPassword: data.newPassword,
      });
      toast.success("Contraseña actualizada");
      resetPwd();
    } catch {
      toast.error("Contraseña actual incorrecta");
    }
    setSavingPwd(false);
  };

  return (
    <div className="flex flex-col h-full pt-14 md:pt-0 overflow-hidden">
      <div className="px-4 md:px-6 py-4 border-b border-border shrink-0">
        <h1 className="font-display text-lg font-semibold text-foreground">Perfil</h1>
      </div>

      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-6 max-w-2xl scrollbar-thin">
        {/* Avatar + info */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-4 mb-8"
        >
          <Avatar className="h-16 w-16">
            <AvatarImage src={user?.image ?? ""} />
            <AvatarFallback className="text-xl bg-primary/20 text-primary font-semibold font-display">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div>
            <p className="font-display font-semibold text-foreground text-lg">{user?.name}</p>
            <p className="text-sm text-muted-foreground">{user?.email}</p>
            {!isLocalUser && (
              <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                <svg width="12" height="12" viewBox="0 0 18 18" fill="none">
                  <rect width="8.5" height="8.5" fill="#F25022" />
                  <rect x="9.5" width="8.5" height="8.5" fill="#7FBA00" />
                  <rect y="9.5" width="8.5" height="8.5" fill="#00A4EF" />
                  <rect x="9.5" y="9.5" width="8.5" height="8.5" fill="#FFB900" />
                </svg>
                Cuenta Microsoft
              </div>
            )}
          </div>
        </motion.div>

        {/* Profile form */}
        <form onSubmit={handleProfile(onSaveProfile)} className="space-y-4 mb-8">
          <h2 className="font-display text-sm font-semibold text-foreground">
            Información personal
          </h2>
          <div className="space-y-1.5">
            <Label htmlFor="fullName">Nombre completo</Label>
            <Input id="fullName" {...regProfile("fullName")} />
            {errProfile.fullName && (
              <p className="text-xs text-destructive">{errProfile.fullName.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label>Correo electrónico</Label>
            <Input value={user?.email ?? ""} disabled className="opacity-70" />
            <p className="text-xs text-muted-foreground">El correo no es modificable.</p>
          </div>
          <Button type="submit" size="sm" disabled={savingProfile || !isDirty} className="gap-1.5">
            {savingProfile ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            Guardar cambios
          </Button>
        </form>

        {/* Change password (only local users) */}
        {isLocalUser && (
          <form onSubmit={handlePwd(onChangePwd)} className="space-y-4">
            <h2 className="font-display text-sm font-semibold text-foreground">
              Cambiar contraseña
            </h2>
            {(["currentPassword", "newPassword", "confirmPassword"] as const).map((field) => (
              <div key={field} className="space-y-1.5">
                <Label htmlFor={field}>
                  {field === "currentPassword" ? "Contraseña actual" :
                   field === "newPassword" ? "Nueva contraseña" : "Confirmar nueva contraseña"}
                </Label>
                <Input
                  id={field}
                  type="password"
                  {...regPwd(field)}
                  className={errPwd[field] ? "border-destructive" : ""}
                />
                {errPwd[field] && (
                  <p className="text-xs text-destructive">{errPwd[field]!.message}</p>
                )}
              </div>
            ))}
            <Button type="submit" size="sm" variant="outline" disabled={savingPwd} className="gap-1.5">
              {savingPwd ? <Loader2 size={13} className="animate-spin" /> : null}
              Actualizar contraseña
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
