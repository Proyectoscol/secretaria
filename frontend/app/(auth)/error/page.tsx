/**
 * Auth error page — shown when NextAuth redirects to /auth/error.
 *
 * Uses inline styles (no Tailwind classes) so it works even if the CSS
 * bundle fails to load during an early prerender.
 *
 * `force-dynamic` prevents Next.js from trying to statically generate this
 * page at build time — `searchParams` is only available at request time.
 */
export const dynamic = "force-dynamic";

const MESSAGES: Record<string, string> = {
  AccessDenied:
    "Tu cuenta no pertenece a una organización autorizada para usar esta aplicación.",
  domain:
    "Tu cuenta no pertenece a una organización autorizada.",
  Configuration:
    "Hay un problema con la configuración del proveedor de autenticación.",
  Verification:
    "El enlace de verificación ha expirado o ya fue usado.",
  Default:
    "Ocurrió un error al iniciar sesión. Intenta de nuevo.",
};

interface PageProps {
  searchParams: Record<string, string | undefined>;
}

export default function AuthErrorPage({ searchParams }: PageProps) {
  const errorCode = searchParams?.error ?? "Default";
  const reason    = searchParams?.reason ?? errorCode;

  const message =
    MESSAGES[errorCode] ??
    MESSAGES[reason]    ??
    MESSAGES.Default;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#09090b",
        fontFamily: "system-ui, -apple-system, sans-serif",
        padding: "1rem",
      }}
    >
      <div
        style={{
          textAlign: "center",
          padding: "2.5rem",
          maxWidth: "420px",
          width: "100%",
          background: "rgba(255,255,255,0.04)",
          borderRadius: "1rem",
          border: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        {/* Icon */}
        <div style={{ fontSize: "2.5rem", marginBottom: "1rem" }}>⚠️</div>

        {/* Heading */}
        <h1
          style={{
            color: "#ffffff",
            fontSize: "1.2rem",
            fontWeight: 600,
            marginBottom: "0.75rem",
            margin: "0 0 0.75rem",
          }}
        >
          Error de autenticación
        </h1>

        {/* Message */}
        <p
          style={{
            color: "#a1a1aa",
            fontSize: "0.9rem",
            lineHeight: 1.6,
            margin: "0 0 2rem",
          }}
        >
          {message}
        </p>

        {/* Back to login */}
        <a
          href="/auth/login"
          style={{
            display: "inline-block",
            padding: "0.55rem 1.5rem",
            backgroundColor: "#f59e0b",
            color: "#000000",
            borderRadius: "0.5rem",
            textDecoration: "none",
            fontWeight: 500,
            fontSize: "0.875rem",
            transition: "opacity 0.15s",
          }}
        >
          Volver al inicio de sesión
        </a>

        {errorCode && errorCode !== "Default" && (
          <p
            style={{
              color: "#52525b",
              fontSize: "0.75rem",
              marginTop: "1.5rem",
            }}
          >
            Código: {errorCode}
          </p>
        )}
      </div>
    </div>
  );
}
