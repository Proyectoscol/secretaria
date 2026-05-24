/**
 * frontend/lib/env-validator.ts — Fail-fast startup env validation.
 *
 * Called from next.config.ts during the Next.js build/start lifecycle
 * so misconfigured deployments fail immediately with a clear error
 * instead of silently serving broken pages.
 *
 * Rules:
 * - Only validates server-side vars (NEXT_PUBLIC_* are validated separately).
 * - Never logs sensitive values — only indicates presence/absence.
 * - Shows ALL errors at once before throwing.
 * - In development, logs warnings instead of throwing so `pnpm dev` still starts.
 */

interface EnvVar {
  name: string;
  required: boolean;
  /** Regex the value must match, if provided */
  pattern?: RegExp;
  description: string;
  sensitive?: boolean;
}

// ── Variable definitions ──────────────────────────────────────────────────────

const SERVER_VARS: EnvVar[] = [
  // Auth
  {
    name: "NEXTAUTH_SECRET",
    required: true,
    description: "NextAuth.js secret for JWT signing (min 32 chars)",
    sensitive: true,
  },
  {
    name: "NEXTAUTH_URL",
    required: true,
    pattern: /^https?:\/\/.+/,
    description: "Canonical URL for NextAuth.js callbacks",
  },

  // Database (Prisma)
  {
    name: "DATABASE_URL",
    required: true,
    pattern: /^postgresql?:\/\/.+/,
    description: "PostgreSQL DSN for Prisma",
    sensitive: true,
  },

  // Librarian backend (server-side only — must NOT have NEXT_PUBLIC_ prefix)
  {
    name: "LIBRARIAN_API_URL",
    required: false,
    pattern: /^https?:\/\/.+/,
    description: "Internal Librarian API URL (default: http://localhost:8001)",
  },
];

const CLIENT_VARS: EnvVar[] = [
  {
    name: "NEXT_PUBLIC_API_URL",
    required: true,
    pattern: /^https?:\/\/.+/,
    description: "Public API base URL exposed to the browser",
  },
];

// ── Validation logic ──────────────────────────────────────────────────────────

function validateVar(v: EnvVar): string | null {
  const value = process.env[v.name];

  if (!value) {
    if (v.required) {
      return `  ✗ ${v.name} — REQUIRED but not set. ${v.description}`;
    }
    return null; // optional + missing = OK
  }

  if (v.pattern && !v.pattern.test(value)) {
    const display = v.sensitive ? `<${value.length} chars>` : JSON.stringify(value);
    return `  ✗ ${v.name} — invalid format (got ${display}). ${v.description}`;
  }

  return null;
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Validate environment variables for the Next.js server.
 * Call this from next.config.ts.
 *
 * Throws in production, warns in development.
 */
export function validateEnv(): void {
  const allVars = [...SERVER_VARS, ...CLIENT_VARS];
  const errors = allVars.map(validateVar).filter((e): e is string => e !== null);

  if (errors.length === 0) return;

  const banner = [
    "",
    "╔══════════════════════════════════════════════════════╗",
    "║  STARTUP ABORTED — environment configuration errors  ║",
    "╚══════════════════════════════════════════════════════╝",
    ...errors,
    "",
    "Fix the above variables in your .env.local file.\n",
  ].join("\n");

  if (process.env.NODE_ENV === "development") {
    // Don't crash dev server — just warn so developers can iterate
    console.warn("\x1b[33m" + banner + "\x1b[0m");
  } else {
    // Production/CI: hard failure
    console.error(banner);
    throw new Error(
      `Environment misconfigured: ${errors.length} variable(s) invalid. See above.`
    );
  }
}
