import { z } from "zod";

const ALLOWED_DOMAINS = (process.env.ALLOWED_EMAIL_DOMAIN ?? "@proyectoscall.com")
  .split(",")
  .map((d) => d.trim().toLowerCase());

export const emailDomainRefinement = (email: string) =>
  ALLOWED_DOMAINS.some((domain) => email.toLowerCase().endsWith(domain));

export const loginSchema = z.object({
  email: z
    .string()
    .email("Email inválido")
    .refine(emailDomainRefinement, {
      message: `Solo se permiten correos corporativos (${ALLOWED_DOMAINS.join(", ")})`,
    }),
  password: z.string().min(1, "Contraseña requerida"),
  rememberMe: z.boolean().default(false),
});

export const registerSchema = z
  .object({
    fullName: z.string().min(2, "Nombre mínimo 2 caracteres").max(100),
    email: z
      .string()
      .email("Email inválido")
      .refine(emailDomainRefinement, {
        message: `Solo se permiten correos de ${ALLOWED_DOMAINS.join(", ")}`,
      }),
    password: z
      .string()
      .min(8, "Mínimo 8 caracteres")
      .regex(/[A-Z]/, "Debe incluir al menos una mayúscula")
      .regex(/[0-9]/, "Debe incluir al menos un número"),
    confirmPassword: z.string(),
  })
  .refine((d) => d.password === d.confirmPassword, {
    message: "Las contraseñas no coinciden",
    path: ["confirmPassword"],
  });

export type LoginInput = z.infer<typeof loginSchema>;
export type RegisterInput = z.infer<typeof registerSchema>;
