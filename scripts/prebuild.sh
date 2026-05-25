#!/usr/bin/env bash
# scripts/prebuild.sh — Prepare the Next.js frontend for a clean Docker build
#
# Resolves known issues that cause the build to fail on a fresh VPS:
#   1. Missing tsconfig.json
#   2. next.config.ts present alongside next.config.mjs (only .mjs is valid)
#   3. Missing package-lock.json (needed for npm ci)
#   4. Stale Geist font import in layout.tsx (Geist is Vercel-only, not Google Fonts)
#
# Usage:
#   bash scripts/prebuild.sh [/path/to/frontend]
#
# The optional argument overrides the frontend directory (default: ./frontend).
# Run this BEFORE `docker build` or `docker compose build`.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[ OK ]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${1:-${REPO_DIR}/frontend}"

cd "$FRONTEND_DIR"
info "Preparando frontend en: $FRONTEND_DIR"

# ── 1. tsconfig.json ──────────────────────────────────────────────────────────
if [ ! -f tsconfig.json ]; then
  info "Creando tsconfig.json…"
  cat > tsconfig.json << 'TSEOF'
{
  "compilerOptions": {
    "target": "es5",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": false,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
TSEOF
  success "tsconfig.json creado"
else
  success "tsconfig.json ya existe"
fi

# ── 2. next.config — prefer .mjs over .ts ─────────────────────────────────────
if [ -f next.config.mjs ]; then
  if [ -f next.config.ts ]; then
    warn "Encontrados next.config.mjs Y next.config.ts — eliminando .ts"
    rm next.config.ts
    success "next.config.ts eliminado (next.config.mjs tiene precedencia)"
  else
    success "next.config.mjs ya existe"
  fi
elif [ -f next.config.ts ]; then
  info "Convirtiendo next.config.ts → next.config.mjs…"
  cat > next.config.mjs << 'NEXTEOF'
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "graph.microsoft.com" },
      { protocol: "https", hostname: "*.microsoft.com" },
    ],
  },
  experimental: {
    serverComponentsExternalPackages: ["bcryptjs", "@prisma/client"],
  },
};
export default nextConfig;
NEXTEOF
  rm next.config.ts
  success "next.config.mjs creado, next.config.ts eliminado"
elif [ ! -f next.config.js ]; then
  info "No se encontró next.config.* — creando next.config.mjs…"
  cat > next.config.mjs << 'NEXTEOF'
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "graph.microsoft.com" },
      { protocol: "https", hostname: "*.microsoft.com" },
    ],
  },
  experimental: {
    serverComponentsExternalPackages: ["bcryptjs", "@prisma/client"],
  },
};
export default nextConfig;
NEXTEOF
  success "next.config.mjs creado"
fi

# ── 3. package-lock.json ──────────────────────────────────────────────────────
if [ ! -f package-lock.json ]; then
  info "Generando package-lock.json (necesario para npm ci en Docker)…"
  if command -v npm &>/dev/null; then
    npm install --package-lock-only --ignore-scripts --quiet
    success "package-lock.json generado"
  else
    warn "npm no encontrado — package-lock.json no se pudo generar"
    warn "El Dockerfile usará npm install (más lento) como fallback"
  fi
else
  success "package-lock.json ya existe"
fi

# ── 4. Geist font in layout.tsx ───────────────────────────────────────────────
# Geist is a Vercel-hosted font, not available in next/font/google.
# If present, replace with Inter which is always available.
LAYOUT_FILE="app/layout.tsx"
if [ -f "$LAYOUT_FILE" ] && grep -q "Geist" "$LAYOUT_FILE" 2>/dev/null; then
  warn "Encontrada fuente 'Geist' en layout.tsx — reemplazando con 'Inter'…"
  sed -i.bak \
    -e 's/import[[:space:]]*{[[:space:]]*\(.*\),*[[:space:]]*Geist[[:space:]]*\(.*\)[[:space:]]*}[[:space:]]*from[[:space:]]*"next\/font\/google"/import { \1\2Inter } from "next\/font\/google"/' \
    -e 's/Geist({/Inter({/' \
    "$LAYOUT_FILE"
  success "Fuente Geist reemplazada con Inter en $LAYOUT_FILE"
else
  if [ -f "$LAYOUT_FILE" ]; then
    success "layout.tsx no usa Geist (sin cambios)"
  fi
fi

# ── 5. Verificar archivos críticos ────────────────────────────────────────────
echo ""
info "Verificando archivos críticos para el build…"
REQUIRED_FILES=(
  "package.json"
  "app/layout.tsx"
  "app/(app)/layout.tsx"
  "lib/auth.ts"
  "prisma/schema.prisma"
)
ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
  if [ -f "$f" ]; then
    success "  $f ✓"
  else
    warn "  FALTA: $f"
    ALL_OK=false
  fi
done

echo ""
if [ "$ALL_OK" = true ]; then
  success "Frontend listo para el build Docker"
else
  warn "Algunos archivos críticos están faltando."
  warn "El build puede fallar — revisa la lista anterior."
fi
