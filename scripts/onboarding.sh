#!/usr/bin/env bash
# =============================================================================
# scripts/onboarding.sh — KOS Interactive Onboarding
# =============================================================================
# Guides an operator from zero to a running KOS + OpenClaw installation on a
# fresh Ubuntu 24 VPS (Docker, Nginx, SSL).
#
# Usage:
#   bash scripts/onboarding.sh
#
# Sections:
#   1  Prerequisites check
#   2  Repository clone / update
#   3  Environment variables (KOS + frontend .env.local)
#   4  OpenRouter — AI model routing & cost management
#   5  Langfuse  — LLM observability & tracing
#   6  Infrastructure services (Redis, ClamAV, GROBID)
#   7  pgweb optional DB inspector
#   8  Database migrations
#   9  Frontend build (Prisma + Next.js)
#  10  All KOS services start
#  11  Nginx + Let's Encrypt SSL
#  12  Mail — Secretario IA (Postfix + Dovecot + OpenDKIM)
#  13  Final health-check & summary
# =============================================================================

set -euo pipefail

# ─── Colours ─────────────────────────────────────────────────────────────────
# Use $'...' (ANSI-C quoting) so variables hold the actual ESC byte (0x1B),
# not the literal string \033. This makes them work in heredocs, printf format
# strings, and echo without -e — not just echo -e.
RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; GREEN=$'\033[0;32m'
CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'

# ALL display functions write to stderr.
# This is critical: several places call prompt_secret / prompt / pick_one via
# command substitution — $(prompt_secret "...").  Any output that goes to
# stdout inside those calls gets captured into the variable.  If warn() wrote
# to stdout (e.g. after a confirm-mismatch) the ANSI ESC bytes would end up
# embedded in an API key, making the generated JSON invalid.
info()    { echo "${CYAN}[INFO]${RESET} $*" >&2; }
success() { echo "${GREEN}[ OK ]${RESET} $*" >&2; }
warn()    { echo "${YELLOW}[WARN]${RESET} $*" >&2; }
error()   { echo "${RED}[ ERR]${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}═══ $* ═══${RESET}\n" >&2; }
note()    { echo "${DIM}      $*${RESET}" >&2; }

confirm() {
  # Print prompt to stderr, read with no -p argument.
  # Using read -p "$(echo ...)" with ESC sequences mis-positions the cursor
  # because bash's read -p doesn't account for non-printable bytes in length.
  local prompt="${1:-Continuar?}"
  local answer
  while true; do
    printf '%s' "${YELLOW}  ${prompt} [s/N]: ${RESET}" >&2
    read -r answer
    case "${answer,,}" in
      s|si|sí|y|yes) return 0 ;;
      n|no|"")        return 1 ;;
      *) echo "  Escribe 's' para sí o 'n' para no." >&2 ;;
    esac
  done
}

prompt() {
  # Usage: VAR=$(prompt VAR_NAME "Prompt text" "default")
  local _var="$1" prompt_text="$2" default="${3:-}"
  local value
  if [[ -n "$default" ]]; then
    printf '%s' "${CYAN}  ${prompt_text} [${default}]: ${RESET}" >&2
    read -r value
    echo "${value:-$default}"
  else
    while true; do
      printf '%s' "${CYAN}  ${prompt_text}: ${RESET}" >&2
      read -r value
      [[ -n "$value" ]] && break
      warn "Este campo es obligatorio."
    done
    echo "$value"
  fi
}

prompt_optional() {
  local prompt_text="$1" default="${2:-}"
  local value
  printf '%s' "${CYAN}  ${prompt_text} [${default:-(dejar vacío)}]: ${RESET}" >&2
  read -r value
  echo "${value:-$default}"
}

prompt_secret() {
  local prompt_text="$1"
  local value confirm_value
  while true; do
    # Print colored prompt via printf to stderr; read silently with no -p prompt.
    # This avoids readline cursor-position bugs when ESC sequences appear in -p.
    printf '%s' "${CYAN}  ${prompt_text}: ${RESET}" >&2
    read -rsp "" value; echo >&2
    printf '%s' "${CYAN}  Confirmar: ${RESET}" >&2
    read -rsp "" confirm_value; echo >&2
    [[ "$value" == "$confirm_value" ]] && break
    warn "Los valores no coinciden. Intenta nuevamente."
  done
  printf '%s' "$value"   # only the secret on stdout; no trailing newline
}

prompt_secret_optional() {
  local prompt_text="$1"
  local value
  printf '%s' "${CYAN}  ${prompt_text} (Enter para omitir): ${RESET}" >&2
  read -rsp "" value; echo >&2
  printf '%s' "$value"
}

pick_one() {
  # pick_one "Prompt" "opt1" "opt2" "opt3" …  → returns chosen value on stdout
  #
  # ALL display output goes to stderr so $(pick_one ...) captures only the
  # selected value. Prompt printed via printf (not read -p) for same reason
  # as the other input helpers above.
  local prompt_text="$1"; shift
  local options=("$@")
  local i=1
  echo "${CYAN}  ${prompt_text}${RESET}" >&2
  for opt in "${options[@]}"; do
    echo "    ${BOLD}$i)${RESET} $opt" >&2
    (( i++ ))
  done
  while true; do
    printf '%s' "${YELLOW}  Elige [1-${#options[@]}]: ${RESET}" >&2
    read -r choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
      echo "${options[$(( choice - 1 ))]}"   # stdout only — the chosen value
      return
    fi
    warn "Opción inválida."
  done
}

# ─── Globals ──────────────────────────────────────────────────────────────────
REPO_DIR="${REPO_DIR:-$(pwd)}"
ENV_FILE="${REPO_DIR}/frontend/.env.local"
KOS_ENV_FILE="${REPO_DIR}/.env.kos"
OPENCLAW_CONFIG_DIR="${HOME}/.openclaw"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG_DIR}/openclaw.json"

# Variables filled in by sections below, used across sections
DOMAIN=""
ALLOWED_DOMAIN=""
MAIL_DOMAIN=""
MAIL_CONFIGURED=0

# ─── Preamble ─────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
cat <<'BANNER'
  ██╗  ██╗ ██████╗ ███████╗
  ██║ ██╔╝██╔═══██╗██╔════╝
  █████╔╝ ██║   ██║███████╗
  ██╔═██╗ ██║   ██║╚════██║
  ██║  ██╗╚██████╔╝███████║
  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
  Knowledge Operating System — Onboarding  (13 pasos)
BANNER
echo -e "${RESET}"
echo "  Este script configura KOS + OpenClaw + OpenRouter + Langfuse"
echo "  en tu VPS de forma interactiva."
echo "  Necesitarás: dominio configurado, credenciales de Microsoft Azure,"
echo "  y acceso a la BD PostgreSQL que usa OpenClaw."
echo
if ! confirm "¿Listo para comenzar?"; then
  echo "Saliendo. Vuelve cuando estés listo."; exit 0
fi

# =============================================================================
# SECCIÓN 1/13 — Prerequisitos del sistema
# =============================================================================
header "1/13 — Verificando prerequisitos del sistema"

check_cmd() {
  if command -v "$1" &>/dev/null; then
    success "$1 encontrado ($(command -v "$1"))"
    return 0
  else
    error "$1 no encontrado"
    return 1
  fi
}

# ── Node.js — instalar automáticamente si no existe ───────────────────────────
if ! command -v node &>/dev/null; then
  info "Node.js no encontrado — instalando Node.js 20 LTS…"
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
  sudo apt-get install -y nodejs >/dev/null 2>&1
  if command -v node &>/dev/null; then
    success "Node.js $(node --version) instalado"
  else
    error "No se pudo instalar Node.js. Instálalo manualmente:"
    note "  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
    note "  sudo apt-get install -y nodejs"
    exit 1
  fi
else
  success "Node.js $(node --version) encontrado"
fi

# ── tmux — instalar si no existe (para comandos largos en SSH) ────────────────
if ! command -v tmux &>/dev/null; then
  info "Instalando tmux (necesario para builds largos en SSH)…"
  sudo apt-get install -y tmux >/dev/null 2>&1 && success "tmux instalado" || warn "No se pudo instalar tmux"
else
  success "tmux $(tmux -V 2>/dev/null | cut -d' ' -f2) encontrado"
fi

MISSING_PREREQS=0
for cmd in docker nginx certbot openssl curl git jq; do
  if ! check_cmd "${cmd}" 2>/dev/null; then
    MISSING_PREREQS=1
  fi
done
# Docker Compose V2 plugin check
if docker compose version &>/dev/null 2>&1; then
  success "docker compose (plugin V2) encontrado"
else
  error "docker compose (plugin V2) no encontrado"
  MISSING_PREREQS=1
fi

if [[ "$MISSING_PREREQS" -eq 1 ]]; then
  warn "Algunos prerequisitos están faltando. ¿Instalarlos automáticamente?"
  if confirm "Instalar prerequisitos (requiere sudo)"; then
    sudo apt-get update -q
    sudo apt-get install -y docker.io docker-compose-v2 nginx certbot \
      python3-certbot-nginx curl git openssl jq
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER"
    warn "Docker fue instalado. Cierra sesión y vuelve a entrar (o ejecuta: newgrp docker),"
    warn "luego vuelve a ejecutar este script."
    exit 0
  else
    error "Instala los prerequisitos manualmente y vuelve a ejecutar el script."
    exit 1
  fi
fi

if ! docker info &>/dev/null; then
  error "El demonio Docker no está corriendo."
  if confirm "¿Iniciarlo ahora?"; then
    sudo systemctl start docker
    sleep 3
    docker info &>/dev/null || { error "No se pudo iniciar Docker."; exit 1; }
    success "Docker iniciado"
  else
    exit 1
  fi
fi

AVAIL_GB=$(df -BG / | awk 'NR==2{gsub("G",""); print $4}')
if [[ "$AVAIL_GB" -lt 10 ]]; then
  warn "Espacio disponible: ${AVAIL_GB}GB. Se recomiendan al menos 10GB."
  confirm "¿Continuar de todas formas?" || exit 1
else
  success "Espacio en disco: ${AVAIL_GB}GB disponibles"
fi

RAM_MB=$(free -m | awk '/Mem:/{print $2}')
if [[ "$RAM_MB" -lt 4000 ]]; then
  warn "RAM disponible: ${RAM_MB}MB. Se recomiendan 4GB para todos los servicios."
else
  success "RAM: ${RAM_MB}MB"
fi

# =============================================================================
# SECCIÓN 2/13 — Repositorio
# =============================================================================
header "2/13 — Repositorio"

if [[ -f "${REPO_DIR}/docker-compose.kos.yml" ]]; then
  success "Repositorio encontrado en: ${REPO_DIR}"
  # Always pull latest fixes before building images.
  # Without this, re-runs would build Docker images from stale source code.
  info "Actualizando repositorio (git pull)…"
  if git -C "$REPO_DIR" pull --ff-only 2>&1 | grep -v "^$" >&2; then
    success "Repositorio actualizado"
  else
    warn "git pull falló (puede que haya cambios locales sin commit). Continuando con la versión actual."
  fi
else
  info "No se encontró el repositorio en el directorio actual."
  CLONE_DIR=$(prompt CLONE_DIR "Directorio de destino" "/opt/kos")
  REPO_URL=$(prompt REPO_URL "URL del repositorio Git" "https://github.com/Proyectoscol/secretaria")
  git clone "$REPO_URL" "$CLONE_DIR"
  REPO_DIR="$CLONE_DIR"
  success "Repositorio clonado en $REPO_DIR"
fi
cd "$REPO_DIR"

# =============================================================================
# SECCIÓN 3/13 — Variables de entorno
# =============================================================================
header "3/13 — Variables de entorno (KOS + frontend)"

echo "Necesitarás los datos de tus dos aplicaciones de Microsoft Azure:"
echo "  • App 1: solo autenticación (openid profile email User.Read)"
echo "  • App 2: permisos de plataforma (offline_access Files.Read.All …)"
echo

DOMAIN=$(prompt DOMAIN "Dominio principal (sin https://)" "tudominio.com")
ALLOWED_DOMAIN=$(prompt ALLOWED_DOMAIN "Dominio de correo permitido (ej: @tuempresa.com)" "@tuempresa.com")

info "Generando NEXTAUTH_SECRET…"
NEXTAUTH_SECRET=$(openssl rand -base64 32)
success "NEXTAUTH_SECRET generado"

DB_URL=$(prompt DB_URL "DATABASE_URL (PostgreSQL)" \
  "postgresql://openclaw:openclaw@localhost:5432/openclaw")

LIBRARIAN_URL=$(prompt LIBRARIAN_URL "LIBRARIAN_API_URL (interno)" "http://localhost:8001")
WS_URL=$(prompt WS_URL "NEXT_PUBLIC_WS_URL" "wss://${DOMAIN}")

echo
info "── Microsoft App 1 (autenticación) ──────────────────────────────"
MS_AUTH_CLIENT_ID=$(prompt MS_AUTH_CLIENT_ID "MICROSOFT_AUTH_CLIENT_ID")
MS_AUTH_CLIENT_SECRET=$(prompt_secret "MICROSOFT_AUTH_CLIENT_SECRET")
MS_AUTH_TENANT=$(prompt MS_AUTH_TENANT "MICROSOFT_AUTH_TENANT_ID" "common")

echo
info "── Microsoft App 2 (permisos de plataforma) ─────────────────────"
MS_PLATFORM_CLIENT_ID=$(prompt MS_PLATFORM_CLIENT_ID "MICROSOFT_PLATFORM_CLIENT_ID")
MS_PLATFORM_CLIENT_SECRET=$(prompt_secret "MICROSOFT_PLATFORM_CLIENT_SECRET")
MS_PLATFORM_TENANT=$(prompt MS_PLATFORM_TENANT "MICROSOFT_PLATFORM_TENANT_ID" "common")

info "Generando MICROSOFT_TOKEN_ENCRYPTION_KEY…"
ENCRYPTION_KEY=$(openssl rand -base64 32)
success "Clave de cifrado AES-256 generada"

FEAT_ONEDRIVE=$(prompt FEAT_ONEDRIVE "NEXT_PUBLIC_FEATURE_ONEDRIVE" "true")
FEAT_MAIL=$(prompt FEAT_MAIL "NEXT_PUBLIC_FEATURE_MAIL" "false")
FEAT_CALENDAR=$(prompt FEAT_CALENDAR "NEXT_PUBLIC_FEATURE_CALENDAR" "false")

mkdir -p "${REPO_DIR}/frontend"
cat > "$ENV_FILE" <<EOF
# Generated by scripts/onboarding.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── NextAuth ──────────────────────────────────────────────────────────────────
NEXTAUTH_URL=https://${DOMAIN}
NEXTAUTH_SECRET=${NEXTAUTH_SECRET}

# ── Backend ────────────────────────────────────────────────────────────────────
NEXT_PUBLIC_API_URL=http://localhost:8000
LIBRARIAN_API_URL=${LIBRARIAN_URL}
NEXT_PUBLIC_WS_URL=${WS_URL}

# ── Microsoft App 1 — Autenticación ───────────────────────────────────────────
MICROSOFT_AUTH_CLIENT_ID=${MS_AUTH_CLIENT_ID}
MICROSOFT_AUTH_CLIENT_SECRET=${MS_AUTH_CLIENT_SECRET}
MICROSOFT_AUTH_TENANT_ID=${MS_AUTH_TENANT}
MICROSOFT_AUTH_SCOPES="openid profile email User.Read"

# ── Microsoft App 2 — Permisos de plataforma ──────────────────────────────────
MICROSOFT_PLATFORM_CLIENT_ID=${MS_PLATFORM_CLIENT_ID}
MICROSOFT_PLATFORM_CLIENT_SECRET=${MS_PLATFORM_CLIENT_SECRET}
MICROSOFT_PLATFORM_TENANT_ID=${MS_PLATFORM_TENANT}
MICROSOFT_PLATFORM_SCOPES="offline_access Files.Read.All Mail.Read Calendars.Read"
MICROSOFT_TOKEN_ENCRYPTION_KEY=${ENCRYPTION_KEY}

# ── Restricción de dominio ─────────────────────────────────────────────────────
ALLOWED_EMAIL_DOMAIN=${ALLOWED_DOMAIN}

# ── Base de datos ──────────────────────────────────────────────────────────────
DATABASE_URL=${DB_URL}

# ── Feature Flags ──────────────────────────────────────────────────────────────
NEXT_PUBLIC_FEATURE_ONEDRIVE=${FEAT_ONEDRIVE}
NEXT_PUBLIC_FEATURE_MAIL=${FEAT_MAIL}
NEXT_PUBLIC_FEATURE_CALENDAR=${FEAT_CALENDAR}
EOF
chmod 600 "$ENV_FILE"
success "frontend/.env.local creado (permisos 600)"

cat > "$KOS_ENV_FILE" <<EOF
# Generated by scripts/onboarding.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
KOS_DB_DSN=${DB_URL}
KOS_REDIS_URL=redis://localhost:6379/0

# ── Mail placeholders — updated in section 12 ─────────────────────────────────
# These are set here with safe defaults so docker compose can interpolate the
# entire kos compose file without emitting "variable is not set" warnings when
# launching infrastructure services (redis, clamav, grobid) in section 6.
MAIL_DOMAIN=${DOMAIN}
MAIL_SECRETARIO_ADDRESS=secretaria@${DOMAIN}
MAIL_SECRETARIO_PASSWORD=changeme_in_section_12
MAIL_SECRETARIO_DISPLAY_NAME=Secretaria IA
MAIL_AUTHORIZED_DOMAINS=${DOMAIN}
EOF
chmod 600 "$KOS_ENV_FILE"
success ".env.kos creado"

# =============================================================================
# SECCIÓN 4/13 — OpenRouter (gestión de modelos y tokens)
# =============================================================================
header "4/13 — OpenRouter — Gestión de modelos de IA"

cat <<'OPENROUTER_INTRO'
  OpenRouter es un proxy unificado de LLMs que permite:
  • Usar Claude, GPT, Gemini, DeepSeek y más desde una sola API key
  • Monitorear uso y costos en tiempo real en openrouter.ai/activity
  • Configurar fallbacks automáticos entre modelos
  • Usar "Auto router" para elegir el modelo más económico por tarea

  OpenClaw tiene soporte nativo. Solo necesitas tu API key y elegir un modelo.
  Más info: https://openrouter.ai/docs/cookbook/coding-agents/openclaw-integration

OPENROUTER_INTRO

if ! confirm "¿Configurar OpenRouter ahora?"; then
  warn "Saltando OpenRouter. Puedes configurarlo después editando ~/.openclaw/openclaw.json"
  OR_API_KEY=""
  OR_MODEL="openrouter/openrouter/auto"
else
  echo
  echo -e "  ${DIM}Obtén tu API key en: https://openrouter.ai/keys${RESET}"
  echo -e "  ${DIM}Las claves comienzan con sk-or-...${RESET}"
  echo
  OR_API_KEY=$(prompt_secret "API Key de OpenRouter (sk-or-...)")

  echo
  info "Modelos disponibles (puedes cambiarlo más tarde):"
  OR_MODEL=$(pick_one "Elige el modelo principal para OpenClaw:" \
    "openrouter/openrouter/auto  ← recomendado (elige el más económico automáticamente)" \
    "openrouter/~anthropic/claude-sonnet-latest  ← Claude Sonnet (mejor calidad)" \
    "openrouter/~anthropic/claude-haiku-latest   ← Claude Haiku (más rápido/barato)" \
    "openrouter/~google/gemini-pro-latest         ← Google Gemini Pro" \
    "openrouter/deepseek/deepseek-chat            ← DeepSeek (muy económico)" \
    "Otro (ingresar manualmente)")

  # Strip the descriptive comment after the model ID
  OR_MODEL=$(echo "$OR_MODEL" | awk '{print $1}')

  if [[ "$OR_MODEL" == "Otro" ]]; then
    OR_MODEL=$(prompt OR_MODEL "ID del modelo (ej: openrouter/~anthropic/claude-opus-latest)")
  fi

  # Optional fallback model
  echo
  info "Modelo de fallback (si el principal no responde):"
  note "Presiona Enter para omitir, o escribe el ID del modelo."
  OR_FALLBACK=$(prompt_optional "Fallback model ID" "openrouter/~anthropic/claude-haiku-latest")

  success "OpenRouter configurado: ${OR_MODEL}"
fi

# =============================================================================
# SECCIÓN 5/13 — Langfuse (observabilidad y trazas de LLM)
# =============================================================================
header "5/13 — Langfuse — Observabilidad de LLM"

cat <<'LANGFUSE_INTRO'
  Langfuse registra cada llamada LLM: prompts, razonamientos, tool-calls,
  latencias y costos. Se integra con OpenRouter a través del "Broadcast"
  de OpenRouter — sin cambios de código, solo configuración.

  Flujo:
    OpenClaw → OpenRouter → (Broadcast) → Langfuse
                  ↓
              Tu modelo (Claude/GPT/etc.)

  Opciones:
  • Langfuse Cloud (gratis hasta cierto límite): https://cloud.langfuse.com
  • Self-hosted: https://langfuse.com/self-hosting

  Más info:
  • https://langfuse.com/integrations/model-gateways/openrouter
  • https://openrouter.ai/docs/features/broadcast

LANGFUSE_INTRO

LF_ENABLED=0
LF_PUBLIC_KEY=""
LF_SECRET_KEY=""
LF_HOST="https://cloud.langfuse.com"

if confirm "¿Configurar Langfuse ahora?"; then
  LF_ENABLED=1
  echo
  LF_MODE=$(pick_one "¿Dónde corre Langfuse?" \
    "Langfuse Cloud (cloud.langfuse.com)" \
    "Self-hosted (URL propia)")

  if [[ "$LF_MODE" == *"Self-hosted"* ]]; then
    LF_HOST=$(prompt LF_HOST "URL de tu instancia Langfuse" "https://langfuse.tuempresa.com")
  fi

  echo
  echo -e "  ${DIM}Obtén tus keys en: ${LF_HOST}/settings → API Keys${RESET}"
  echo
  LF_PUBLIC_KEY=$(prompt LF_PUBLIC_KEY "Langfuse Public Key (pk-lf-...)")
  LF_SECRET_KEY=$(prompt_secret "Langfuse Secret Key (sk-lf-...)")

  success "Langfuse configurado: ${LF_HOST}"

  cat <<LANGFUSE_NEXT

  ${BOLD}Paso manual requerido — Configura el Broadcast en OpenRouter:${RESET}
  ${DIM}(Solo necesitas hacer esto una vez en el panel web de OpenRouter)${RESET}

  1. Ve a https://openrouter.ai/settings (pestaña "Integrations" o "Broadcast")
  2. Haz clic en "Add Integration" → selecciona Langfuse
  3. Ingresa:
       Host:       ${LF_HOST}
       Public Key: ${LF_PUBLIC_KEY}
       Secret Key: ••••••••••••••••
  4. Guarda los cambios.

  Una vez configurado, TODAS las llamadas LLM que pasen por OpenRouter
  aparecerán automáticamente en tu proyecto de Langfuse.
  URL de trazas: ${LF_HOST}/traces

LANGFUSE_NEXT
  confirm "¿Listo? (presiona 's' cuando hayas configurado el Broadcast)" || true
else
  warn "Saltando Langfuse. Puedes configurarlo después en https://openrouter.ai/settings"
fi

# =============================================================================
# Escribir ~/.openclaw/openclaw.json con OpenRouter + Langfuse
# =============================================================================
if [[ -n "$OR_API_KEY" ]]; then
  info "Escribiendo configuración de OpenClaw…"
  mkdir -p "$OPENCLAW_CONFIG_DIR"
  chmod 700 "$OPENCLAW_CONFIG_DIR"

  # Build the fallback block only if OR_FALLBACK was given
  if [[ -n "${OR_FALLBACK:-}" ]]; then
    FALLBACK_BLOCK=$(cat <<JSON
,
        "fallbacks": ["${OR_FALLBACK}"]
JSON
)
    FALLBACK_MODEL_ENTRY=$(cat <<JSON
,
        "${OR_FALLBACK}": {}
JSON
)
  else
    FALLBACK_BLOCK=""
    FALLBACK_MODEL_ENTRY=""
  fi

  # Build Langfuse env block only if enabled
  if [[ "$LF_ENABLED" -eq 1 ]]; then
    LF_ENV_BLOCK=$(cat <<JSON
,
    "LANGFUSE_PUBLIC_KEY": "${LF_PUBLIC_KEY}",
    "LANGFUSE_SECRET_KEY": "${LF_SECRET_KEY}",
    "LANGFUSE_HOST": "${LF_HOST}"
JSON
)
  else
    LF_ENV_BLOCK=""
  fi

  # If config already exists, back it up
  if [[ -f "$OPENCLAW_CONFIG" ]]; then
    cp "$OPENCLAW_CONFIG" "${OPENCLAW_CONFIG}.bak.$(date +%s)"
    warn "Config anterior respaldado como ${OPENCLAW_CONFIG}.bak.*"
  fi

  # ── Limpiar valores antes de escribir en JSON ──────────────────────────────
  # Las API keys pegadas por el usuario pueden contener saltos de línea,
  # espacios y caracteres invisibles que corrumpen el JSON con heredoc.
  # printf con %s es el único método 100% seguro para esto.
  OR_API_KEY_CLEAN=$(echo "$OR_API_KEY" | tr -d '[:space:]' | tr -d '\r')
  OR_MODEL_CLEAN=$(echo "$OR_MODEL"     | tr -d '\r\n')
  if [[ -n "${OR_FALLBACK:-}" ]]; then
    OR_FALLBACK_CLEAN=$(echo "$OR_FALLBACK" | tr -d '\r\n')
  else
    OR_FALLBACK_CLEAN=""
  fi

  if [[ "$LF_ENABLED" -eq 1 ]]; then
    LF_PUBLIC_KEY_CLEAN=$(echo "$LF_PUBLIC_KEY" | tr -d '[:space:]' | tr -d '\r')
    LF_SECRET_KEY_CLEAN=$(echo "$LF_SECRET_KEY" | tr -d '[:space:]' | tr -d '\r')
  fi

  # Build JSON with printf — no heredoc, no variable expansion surprises
  {
    printf '{\n'
    printf '  "env": {\n'
    printf '    "OPENROUTER_API_KEY": "%s"' "$OR_API_KEY_CLEAN"
    if [[ "$LF_ENABLED" -eq 1 ]]; then
      printf ',\n    "LANGFUSE_PUBLIC_KEY": "%s"' "$LF_PUBLIC_KEY_CLEAN"
      printf ',\n    "LANGFUSE_SECRET_KEY": "%s"' "$LF_SECRET_KEY_CLEAN"
      printf ',\n    "LANGFUSE_HOST": "%s"'        "$LF_HOST"
    fi
    printf '\n  },\n'
    printf '  "agents": {\n'
    printf '    "defaults": {\n'
    printf '      "model": {\n'
    printf '        "primary": "%s"' "$OR_MODEL_CLEAN"
    if [[ -n "$OR_FALLBACK_CLEAN" ]]; then
      printf ',\n        "fallbacks": ["%s"]' "$OR_FALLBACK_CLEAN"
    fi
    printf '\n      },\n'
    printf '      "models": {\n'
    printf '        "%s": {}' "$OR_MODEL_CLEAN"
    if [[ -n "$OR_FALLBACK_CLEAN" ]]; then
      printf ',\n        "%s": {}' "$OR_FALLBACK_CLEAN"
    fi
    printf '\n      }\n'
    printf '    }\n'
    printf '  }\n'
    printf '}\n'
  } > "$OPENCLAW_CONFIG"

  chmod 600 "$OPENCLAW_CONFIG"
  success "~/.openclaw/openclaw.json escrito (permisos 600)"

  # Validate JSON before continuing
  if command -v python3 &>/dev/null; then
    if python3 -m json.tool "$OPENCLAW_CONFIG" >/dev/null 2>&1; then
      success "JSON válido ✓"
    else
      error "El JSON generado no es válido — escribiendo versión mínima de emergencia"
      printf '{\n  "env": {\n    "OPENROUTER_API_KEY": "%s"\n  },\n  "agents": {\n    "defaults": {\n      "model": {\n        "primary": "anthropic/claude-sonnet-4-5"\n      }\n    }\n  }\n}\n' \
        "$OR_API_KEY_CLEAN" > "$OPENCLAW_CONFIG"
      warn "JSON mínimo escrito. Verifica y edita manualmente: nano ${OPENCLAW_CONFIG}"
    fi
  elif command -v jq &>/dev/null; then
    if jq empty "$OPENCLAW_CONFIG" 2>/dev/null; then
      success "JSON válido ✓"
    else
      error "El JSON generado no es válido. Revisa ${OPENCLAW_CONFIG}"
    fi
  fi

  info "Verifica la configuración con:"
  note "  cat ${OPENCLAW_CONFIG}"
  note "  openclaw agent --message 'hola' --thinking low    # prueba rápida"
else
  warn "OpenRouter no configurado. OpenClaw usará el proveedor predeterminado."
  warn "Para configurarlo más tarde:"
  note "  mkdir -p ~/.openclaw"
  note "  nano ~/.openclaw/openclaw.json"
  note "  (Ejemplo en: https://openrouter.ai/docs/cookbook/coding-agents/openclaw-integration)"
fi

# =============================================================================
# SECCIÓN 6/13 — Servicios de infraestructura (Redis, ClamAV, GROBID)
# =============================================================================
header "6/13 — Servicios de infraestructura"

info "Levantando Redis, ClamAV, GROBID…"
info "Primera vez: ClamAV descarga ~200 MB de definiciones de virus. Ten paciencia."

# --env-file suprime los warnings "variable is not set" para variables de correo
# que aún no están configuradas pero están referenciadas en el compose file.
docker compose --env-file "$KOS_ENV_FILE" -f docker-compose.kos.yml up -d redis clamav grobid

info "Esperando a que Redis esté disponible…"
REDIS_READY=0
for i in $(seq 1 30); do
  if docker compose --env-file "$KOS_ENV_FILE" -f docker-compose.kos.yml exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
    REDIS_READY=1; break
  fi
  sleep 2
done
if [[ "$REDIS_READY" -eq 0 ]]; then
  error "Redis no respondió en 60s. Revisa: docker compose -f docker-compose.kos.yml logs redis"
  exit 1
fi
success "Redis OK"

info "Esperando a que ClamAV descargue definiciones (puede tardar 3-5 min)…"
CLAM_READY=0
for i in $(seq 1 60); do
  if docker compose --env-file "$KOS_ENV_FILE" -f docker-compose.kos.yml exec -T clamav clamdscan --ping 3 &>/dev/null; then
    CLAM_READY=1; break
  fi
  sleep 5
done
if [[ "$CLAM_READY" -eq 0 ]]; then
  warn "ClamAV no respondió aún. Puede estar descargando definiciones."
  warn "Los documentos no se procesarán hasta que ClamAV esté listo."
fi

success "Infraestructura iniciada"

# =============================================================================
# SECCIÓN 7/13 — pgweb (inspector de BD opcional)
# =============================================================================
header "7/13 — Inspector de base de datos (opcional)"

if confirm "¿Levantar pgweb para inspeccionar la BD desde el navegador?"; then
  docker run -d --name kos-pgweb \
    -e DATABASE_URL="${DB_URL}" \
    -p 127.0.0.1:8080:8081 \
    sosedoff/pgweb 2>/dev/null \
    && success "pgweb disponible en http://localhost:8080" \
    || warn "No se pudo iniciar pgweb — omitiendo"
else
  info "pgweb omitido"
fi

# =============================================================================
# SECCIÓN 8/13 — Migraciones de base de datos
# =============================================================================
header "8/13 — Migraciones de base de datos"

info "Verificando conexión a PostgreSQL…"
DB_PASS=$(echo "$DB_URL" | grep -oP '(?<=:)[^:@]+(?=@)' || true)
if ! docker run --rm --net=host \
    -e PGPASSWORD="${DB_PASS}" \
    postgres:16-alpine psql "$DB_URL" -c "SELECT 1" &>/dev/null; then
  error "No se pudo conectar a PostgreSQL: ${DB_URL}"
  error "Verifica que la BD esté corriendo y las credenciales sean correctas."
  exit 1
fi
success "Conexión a PostgreSQL OK"

run_migration() {
  local file="$1"
  info "Aplicando ${file}…"
  docker run --rm --net=host \
    -e PGPASSWORD="${DB_PASS}" \
    -v "${REPO_DIR}/migrations:/migrations:ro" \
    postgres:16-alpine \
    psql "$DB_URL" -f "/migrations/${file}"
  success "${file} aplicado"
}

run_migration "001_kos_schema.sql"
run_migration "002_users_auth.sql"

# =============================================================================
# SECCIÓN 9/13 — Build y migraciones de Prisma (Next.js)
# =============================================================================
header "9/13 — Build del frontend (Prisma + Next.js)"

info "Preparando frontend para el build (scripts/prebuild.sh)…"
bash "${REPO_DIR}/scripts/prebuild.sh" "${REPO_DIR}/frontend"

info "Verificando archivos críticos antes del build…"
REQUIRED_BUILD_FILES=(
  "frontend/next.config.mjs"
  "frontend/tsconfig.json"
  "frontend/package.json"
  "frontend/package-lock.json"
  "frontend/public/.gitkeep"
  "frontend/app/layout.tsx"
  "frontend/app/(app)/layout.tsx"
  "frontend/app/auth/error/page.tsx"
  "frontend/app/auth/login/page.tsx"
  "frontend/stores/chat.ts"
  "frontend/lib/auth.ts"
  "frontend/components/chat/MessageBubble.tsx"
  "frontend/components/chat/ChatInput.tsx"
  "frontend/components/chat/LibrarianStatusBar.tsx"
  "frontend/components/ui/button.tsx"
  "frontend/components/ui/sonner.tsx"
)
BUILD_FILES_OK=true
for _f in "${REQUIRED_BUILD_FILES[@]}"; do
  if [[ ! -f "${REPO_DIR}/${_f}" ]]; then
    error "Falta: ${_f}"
    BUILD_FILES_OK=false
  fi
done
if [[ "$BUILD_FILES_OK" = false ]]; then
  error "Archivos críticos faltantes — el build fallará. Revisa la lista anterior."
  exit 1
fi
success "Todos los archivos críticos presentes ✓"

info "Construyendo imagen Docker del frontend…"
info "Primera vez: puede tardar 5-10 minutos (descarga node:20-alpine, npm install)."

docker build \
  -t kos-frontend:latest \
  -f "${REPO_DIR}/frontend/Dockerfile.frontend" \
  "${REPO_DIR}/frontend"
success "Imagen kos-frontend:latest construida"

info "Aplicando migraciones Prisma…"
# The kos-frontend:latest runner image only has the Next.js standalone build —
# no prisma/schema.prisma and no node_modules/.bin/prisma.
# Run prisma directly on the host (Node.js is guaranteed by section 1).
# Use the exact version from frontend/package.json to avoid Prisma 7.x API
# breakage (7.x changed the schema-discovery flow and removed --skip-generate).
PRISMA_SCHEMA="${REPO_DIR}/frontend/prisma/schema.prisma"
if [[ ! -f "$PRISMA_SCHEMA" ]]; then
  warn "prisma/schema.prisma no encontrado — omitiendo migraciones Prisma"
else
  PRISMA_VER=$(jq -r '.dependencies.prisma // .devDependencies.prisma // "5"' \
    "${REPO_DIR}/frontend/package.json" 2>/dev/null | tr -d '\r\n' || echo "5")
  info "Usando Prisma ${PRISMA_VER} (desde package.json)…"
  (
    cd "${REPO_DIR}/frontend"
    DATABASE_URL="${DB_URL}" \
      npx -y "prisma@${PRISMA_VER}" migrate deploy \
        --schema="prisma/schema.prisma" \
    || DATABASE_URL="${DB_URL}" \
      npx -y "prisma@${PRISMA_VER}" db push \
        --schema="prisma/schema.prisma" --accept-data-loss
  )
  success "Migraciones Prisma aplicadas"
fi

# =============================================================================
# SECCIÓN 10/13 — Todos los servicios KOS
# =============================================================================
header "10/13 — Iniciando todos los servicios KOS"

info "Construyendo imagen Python (Dockerfile.kos)…"
info "Primera vez: descarga sentence-transformers (~400 MB). Sé paciente."
docker build \
  -t kos-python:latest \
  -f "${REPO_DIR}/Dockerfile.kos" \
  "${REPO_DIR}"
success "Imagen kos-python:latest construida"

info "Levantando celery_worker, librarian_api y frontend…"
docker compose --env-file "$KOS_ENV_FILE" -f docker-compose.kos.yml up -d celery_worker librarian_api frontend
success "Servicios KOS iniciados"

info "Esperando al Librarian API (puerto 8001)…"
LIBRARIAN_READY=0
for i in $(seq 1 30); do
  if curl -sf "http://localhost:8001/internal/librarian/health" &>/dev/null; then
    LIBRARIAN_READY=1; break
  fi
  sleep 3
done
if [[ "$LIBRARIAN_READY" -eq 0 ]]; then
  error "Librarian API no respondió en 90s."
  error "Últimas líneas del log:"
  docker compose --env-file "$KOS_ENV_FILE" -f docker-compose.kos.yml logs --tail=40 librarian_api >&2 || true
  exit 1
fi
success "Librarian API OK"

info "Esperando al frontend Next.js (puerto 3000)…"
for i in $(seq 1 30); do
  curl -sf "http://localhost:3000" &>/dev/null && break
  sleep 3
done

# =============================================================================
# SECCIÓN 11/13 — Nginx + SSL
# =============================================================================
header "11/13 — Nginx + SSL (Let's Encrypt)"

info "Configurando Nginx para ${DOMAIN}…"

NGINX_CONF="/etc/nginx/sites-available/kos"
sudo tee "$NGINX_CONF" > /dev/null <<NGINXCONF
# Generated by scripts/onboarding.sh
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN} www.${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self' wss://${DOMAIN}; frame-ancestors 'none';" always;

    client_max_body_size 110m;

    location / {
        proxy_pass         http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection 'upgrade';
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
        proxy_read_timeout 120s;
    }

    location /ws/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "Upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 3600s;
    }

    location /_next/static/ {
        proxy_pass       http://127.0.0.1:3000;
        expires          365d;
        add_header       Cache-Control "public, immutable";
        access_log       off;
    }

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
}
NGINXCONF

sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/kos
sudo nginx -t && sudo systemctl reload nginx
success "Nginx configurado para ${DOMAIN}"

if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  success "Certificado SSL ya existe para ${DOMAIN}"
else
  if confirm "¿Obtener certificado SSL de Let's Encrypt para ${DOMAIN}?"; then
    EMAIL=$(prompt EMAIL "Email para Let's Encrypt (notificaciones de renovación)")
    sudo certbot --nginx -d "${DOMAIN}" -d "www.${DOMAIN}" \
      --email "$EMAIL" --agree-tos --non-interactive
    success "Certificado SSL obtenido para ${DOMAIN}"
  else
    warn "Saltando Let's Encrypt. HTTPS no estará disponible hasta obtener un certificado."
  fi
fi

sudo systemctl reload nginx
success "Nginx recargado"

# =============================================================================
# SECCIÓN 12/13 — Sistema de correo — Secretario IA
# =============================================================================
header "12/13 — Sistema de correo — Secretario IA"

cat <<'MAIL_INTRO'
  El Secretario IA necesita un servidor de correo self-hosted para:
  • Enviar reportes y alertas a tu equipo
  • Recibir y procesar solicitudes por email
  • Integrar adjuntos al pipeline de ingestión KOS

  Componentes: Postfix + Dovecot + OpenDKIM + Rspamd
  Documentación completa: docs/dns_setup.md

MAIL_INTRO

if ! confirm "¿Configurar el sistema de correo ahora?"; then
  warn "Saltando sistema de correo. Puedes configurarlo después."
  warn "Guía: bash scripts/dns_check.sh tu-dominio.com tu-ip"
else
  MAIL_CONFIGURED=1

  # ── 1. Dominio de correo ──────────────────────────────────────────────────
  echo
  MAIL_DOMAIN=$(prompt_optional "Dominio de correo (ej: empresa.com)" "${DOMAIN}")
  VPS_IP=$(prompt_optional "IP pública de tu VPS" "")

  # ── 2. Verificar DNS ───────────────────────────────────────────────────────
  echo
  info "Verificando configuración DNS para ${MAIL_DOMAIN}…"
  echo
  if bash "${REPO_DIR}/scripts/dns_check.sh" "${MAIL_DOMAIN}" "${VPS_IP}" 2>/dev/null; then
    success "DNS verificado correctamente"
  else
    warn "Algunos registros DNS no están correctamente configurados."
    warn "Ver guía completa en: docs/dns_setup.md"
    if ! confirm "¿Continuar de todas formas (el correo puede no funcionar hasta corregir DNS)?"; then
      MAIL_CONFIGURED=0
    fi
  fi

  if [[ "$MAIL_CONFIGURED" -eq 1 ]]; then
    # ── 3. Generar claves DKIM ─────────────────────────────────────────────
    echo
    if [[ -f "${REPO_DIR}/mail/opendkim/keys/${MAIL_DOMAIN}/private.key" ]]; then
      success "Claves DKIM ya existen para ${MAIL_DOMAIN}"
    else
      info "Generando claves DKIM para ${MAIL_DOMAIN}…"
      bash "${REPO_DIR}/scripts/generate_dkim.sh" "${MAIL_DOMAIN}"
      echo
      warn "⚠  IMPORTANTE: Agrega el registro TXT de DKIM mostrado arriba en tu DNS"
      warn "   antes de continuar. Esto es crítico para que tus correos no vayan a spam."
      confirm "¿Has agregado el registro DKIM en DNS? (puedes omitirlo y agregarlo después)" || true
    fi

    # ── 4. Credenciales del buzón ─────────────────────────────────────────
    echo
    info "── Buzón del Secretario IA ──────────────────────────────────────"
    MAIL_ADDRESS=$(prompt_optional "Dirección del Secretario" "secretaria@${MAIL_DOMAIN}")
    MAIL_PASS=$(prompt_secret "Contraseña del buzón (mín 12 caracteres)")
    MAIL_DISPLAY=$(prompt_optional "Nombre del Secretario" "Secretaria IA")

    echo
    info "── Dominios autorizados para enviar correos al Secretario ───────"
    note "  Separa múltiples dominios con coma. Ej: empresa.com,cliente.co"
    note "  Solo correos de estos dominios serán procesados por el Secretario."
    MAIL_AUTHORIZED_DOMAINS=$(prompt_optional "Dominios autorizados" "${MAIL_DOMAIN}")
    while [[ -z "$MAIL_AUTHORIZED_DOMAINS" ]]; do
      warn "Debes ingresar al menos un dominio autorizado."
      MAIL_AUTHORIZED_DOMAINS=$(prompt_optional "Dominios autorizados" "${MAIL_DOMAIN}")
    done

    # ── 5. Verificar puerto 25 ────────────────────────────────────────────
    echo
    info "Verificando que el puerto 25 esté abierto en ${VPS_IP}…"
    if command -v nc &>/dev/null && [[ -n "$VPS_IP" ]]; then
      if nc -zw5 "${VPS_IP}" 25 2>/dev/null; then
        success "Puerto 25 abierto ✓"
      else
        warn "Puerto 25 cerrado o filtrado."
        warn "Solicita la apertura al soporte de tu proveedor de VPS."
        warn "Ver: docs/dns_setup.md — sección 'Apertura del puerto 25'"
      fi
    else
      note "No se pudo verificar el puerto 25 (nc no disponible o IP no especificada)"
    fi

    # ── 6. Escribir variables de entorno de correo ────────────────────────
    echo
    info "Agregando configuración de correo a .env.kos…"
    cat >> "$KOS_ENV_FILE" <<MAILENV

# ── Sistema de correo — Secretario IA ────────────────────────────────────────
MAIL_DOMAIN=${MAIL_DOMAIN}
MAIL_SECRETARIO_ADDRESS=${MAIL_ADDRESS}
MAIL_SECRETARIO_PASSWORD=${MAIL_PASS}
MAIL_SECRETARIO_DISPLAY_NAME=${MAIL_DISPLAY}
MAIL_AUTHORIZED_DOMAINS=${MAIL_AUTHORIZED_DOMAINS}
MAIL_RECEIVE_MODE=imap
MAIL_POLL_INTERVAL_SECONDS=30
MAIL_MAX_DAILY_OUTBOUND=500
MAIL_REPORT_TIMEZONE=America/Bogota
MAIL_SMTP_HOST=postfix
MAIL_SMTP_PORT=587
MAIL_IMAP_HOST=dovecot
MAIL_IMAP_PORT=993
MAIL_REPORT_RECIPIENTS_DAILY=${MAIL_ADDRESS}
MAILENV
    chmod 600 "$KOS_ENV_FILE"
    success "Variables de correo guardadas en .env.kos"

    # ── DNS guidance table ────────────────────────────────────────────────
    echo ""
    echo -e "${BOLD}${CYAN}═══ DNS — Registros requeridos en tu proveedor de dominio ═══${RESET}"
    echo ""
    echo "  Configura estos registros en tu proveedor (Hostinger, GoDaddy, Cloudflare…)."
    echo "  Los servicios NO funcionarán hasta tener DNS correcto."
    echo ""
    echo -e "  ${DIM}┌──────┬──────────────────────────────┬──────────────────────────────┐${RESET}"
    echo -e "  ${DIM}│ Tipo │ Nombre                       │ Valor                        │${RESET}"
    echo -e "  ${DIM}├──────┼──────────────────────────────┼──────────────────────────────┤${RESET}"
    printf   "  ${DIM}│${RESET} %-4s ${DIM}│${RESET} %-28s ${DIM}│${RESET} %-28s ${DIM}│${RESET}\n" "A"     "@"                           "${VPS_IP:-<tu-ip-vps>}"
    printf   "  ${DIM}│${RESET} %-4s ${DIM}│${RESET} %-28s ${DIM}│${RESET} %-28s ${DIM}│${RESET}\n" "A"     "mail"                         "${VPS_IP:-<tu-ip-vps>}"
    printf   "  ${DIM}│${RESET} %-4s ${DIM}│${RESET} %-28s ${DIM}│${RESET} %-28s ${DIM}│${RESET}\n" "A"     "www"                          "${VPS_IP:-<tu-ip-vps>}"
    printf   "  ${DIM}│${RESET} %-4s ${DIM}│${RESET} %-28s ${DIM}│${RESET} %-28s ${DIM}│${RESET}\n" "MX"    "@"                           "10 mail.${MAIL_DOMAIN}"
    printf   "  ${DIM}│${RESET} %-4s ${DIM}│${RESET} %-28s ${DIM}│${RESET} %-28s ${DIM}│${RESET}\n" "TXT"   "@"                           "v=spf1 mx -all"
    printf   "  ${DIM}│${RESET} %-4s ${DIM}│${RESET} %-28s ${DIM}│${RESET} %-28s ${DIM}│${RESET}\n" "TXT"   "openclaw._domainkey"          "[ver DKIM arriba]"
    echo -e "  ${DIM}└──────┴──────────────────────────────┴──────────────────────────────┘${RESET}"
    echo ""
    echo -e "  ${YELLOW}⚠  PTR (reverse DNS):${RESET} configura en Hostinger → VPS → Reverse DNS"
    echo -e "     Valor: ${BOLD}mail.${MAIL_DOMAIN}${RESET}"
    echo ""
    note "  Verificar DNS después: bash scripts/dns_check.sh ${MAIL_DOMAIN} ${VPS_IP:-<ip>}"

    # ── 7. Aplicar migraciones de correo y seguridad ──────────────────────
    echo
    if confirm "¿Aplicar migraciones de base de datos para el sistema de correo y seguridad? (003 + 004)"; then
      # $DB_URL is the PostgreSQL DSN set as a shell variable in section 3.
      # $KOS_DB_DSN is only a file variable in .env.kos — not available in the shell.
      DB_PASS=$(echo "$DB_URL" | grep -oP '(?<=:)[^:@]+(?=@)' || true)
      if docker run --rm --net=host \
          -e PGPASSWORD="${DB_PASS}" \
          -v "${REPO_DIR}/migrations:/migrations:ro" \
          postgres:16-alpine \
          psql "$DB_URL" -f "/migrations/003_mail_schema.sql"; then
        success "003_mail_schema.sql aplicado"
      else
        error "Error aplicando migración 003_mail_schema.sql"
        warn "Puedes aplicarla manualmente: psql \$DB_URL < migrations/003_mail_schema.sql"
      fi

      # 004 — token isolation, audit log, notifications
      echo
      info "Aplicando migración de aislamiento de tokens (004_token_isolation.sql)…"
      if docker run --rm --net=host \
          -e PGPASSWORD="${DB_PASS}" \
          -v "${REPO_DIR}/migrations:/migrations:ro" \
          postgres:16-alpine \
          psql "$DB_URL" -f "/migrations/004_token_isolation.sql"; then
        success "004_token_isolation.sql aplicado"
        info "  → task_execution_log, user_notifications, columnas de auditoría en microsoft_platform_tokens"
      else
        error "Error aplicando migración 004_token_isolation.sql"
        warn "Puedes aplicarla manualmente: psql \$DB_URL < migrations/004_token_isolation.sql"
        warn "IMPORTANTE: Esta migración es requerida para el aislamiento de tokens Microsoft."
      fi
    fi

    # ── 8. Levantar servicios de correo ───────────────────────────────────
    # --env-file is required here: compose maps MAIL_SECRETARIO_ADDRESS/PASSWORD
    # from the env file, but the shell variables use different names ($MAIL_ADDRESS,
    # $MAIL_PASS). Without --env-file the services would start with empty credentials.
    echo
    info "Construyendo y levantando servicios de correo…"
    info "(Primera vez: puede tardar 2-3 minutos)"
    docker compose --env-file "$KOS_ENV_FILE" -f "${REPO_DIR}/docker-compose.kos.yml" up -d \
      postfix dovecot opendkim rspamd celery_beat

    # Health check
    sleep 10
    if docker compose --env-file "$KOS_ENV_FILE" -f "${REPO_DIR}/docker-compose.kos.yml" ps postfix 2>/dev/null \
        | grep -q "Up\|running"; then
      success "Postfix activo"
    else
      warn "Postfix no confirmado — revisa: docker compose logs postfix"
    fi

    if docker compose --env-file "$KOS_ENV_FILE" -f "${REPO_DIR}/docker-compose.kos.yml" ps dovecot 2>/dev/null \
        | grep -q "Up\|running"; then
      success "Dovecot activo"
    else
      warn "Dovecot no confirmado — revisa: docker compose logs dovecot"
    fi

    success "Celery Beat iniciado (reportes y polling programados)"

    # ── 9. Correo de prueba ───────────────────────────────────────────────
    echo
    if confirm "¿Enviar un correo de prueba?"; then
      TEST_EMAIL=$(prompt_optional "Email de destino" "")
      if [[ -n "$TEST_EMAIL" ]]; then
        echo "Prueba de correo — KOS Secretario IA" | \
          docker exec -i postfix sendmail -f "${MAIL_ADDRESS}" "${TEST_EMAIL}" 2>/dev/null \
          && success "Correo de prueba enviado a ${TEST_EMAIL}" \
          || warn "Error al enviar correo de prueba — verifica los logs de Postfix"
        echo
        note "Si el correo llegó a spam: la IP necesita 2-4 semanas para ganar reputación."
        note "Verificar entregabilidad: https://www.mail-tester.com"
      fi
    fi
  fi
fi

# =============================================================================
# SECCIÓN 13/13 — Verificación final y resumen
# =============================================================================
header "13/13 — Verificación final"

ALL_OK=1

check_service() {
  local name="$1" url="$2"
  if curl -sf "$url" &>/dev/null; then
    success "✓ ${name}: ${url}"
  else
    error "✗ ${name}: ${url} no responde"
    ALL_OK=0
  fi
}

check_service "Librarian API (salud)" "http://localhost:8001/internal/librarian/health"
check_service "Frontend (Next.js)"   "http://localhost:3000"

HTTPS_OK=0
if curl -sf --max-time 10 "https://${DOMAIN}" &>/dev/null; then
  CERT_EXPIRY=$(echo | openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  success "✓ Frontend HTTPS activo: https://${DOMAIN}"
  [[ -n "${CERT_EXPIRY}" ]] && note "  Certificado SSL expira: ${CERT_EXPIRY}"
  HTTPS_OK=1
else
  warn "  HTTPS no disponible en https://${DOMAIN}"
  note "  Si certbot acaba de correr, espera ~30 s y verifica manualmente:"
  note "  curl -Iv https://${DOMAIN}"
fi

echo
echo -e "${BOLD}Servicios Docker en ejecución:${RESET}"
docker compose -f docker-compose.kos.yml ps

echo
if [[ "$ALL_OK" -eq 1 ]]; then
  echo -e "${GREEN}${BOLD}"
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  🎉  ¡KOS está corriendo correctamente!                     ║"
  echo "╠══════════════════════════════════════════════════════════════╣"
  if [[ "${HTTPS_OK}" -eq 1 ]]; then
  printf "║  Frontend:      https://%-36s║\n" "${DOMAIN}"
  else
  printf "║  Frontend:      http://%-37s║\n" "${DOMAIN}  (sin SSL)"
  fi
  echo "║  Librarian API: http://localhost:8001                       ║"
  echo "║  Redis:         localhost:6379                              ║"
  if [[ -n "${OR_API_KEY:-}" ]]; then
  echo "║  OpenRouter:    https://openrouter.ai/activity              ║"
  fi
  if [[ "$LF_ENABLED" -eq 1 ]]; then
  printf "║  Langfuse:      %-44s║\n" "${LF_HOST}"
  fi
  if [[ "$MAIL_CONFIGURED" -eq 1 ]]; then
  printf "║  Secretario:    smtp://%-37s║\n" "${MAIL_DOMAIN:-mail}"
  fi
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo -e "${RESET}"
else
  echo -e "${YELLOW}${BOLD}"
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  ⚠  KOS iniciado con advertencias                           ║"
  echo "╠══════════════════════════════════════════════════════════════╣"
  echo "║  Revisa los servicios que fallaron arriba.                   ║"
  echo "║  Logs: docker compose -f docker-compose.kos.yml logs        ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo -e "${RESET}"
fi

echo -e "${CYAN}${BOLD}Próximos pasos:${RESET}"
echo
echo "  1. Crea el primer usuario admin:"
echo "       curl -X POST https://${DOMAIN}/api/auth/register \\"
echo "         -H 'Content-Type: application/json' \\"
echo "         -d '{\"fullName\":\"Admin\",\"email\":\"admin@${ALLOWED_DOMAIN#@}\",\"password\":\"...\",\"confirmPassword\":\"...\"}'"
echo
echo "  2. Configura renovación automática de SSL:"
echo "       sudo systemctl enable certbot.timer"
echo
if [[ -n "${OR_API_KEY:-}" ]]; then
echo "  3. Monitorea uso y costos de LLM:"
echo "       https://openrouter.ai/activity"
echo
fi
if [[ "$LF_ENABLED" -eq 1 ]]; then
echo "  4. Revisa trazas de agente en Langfuse:"
echo "       ${LF_HOST}/traces"
echo
fi
if [[ "$MAIL_CONFIGURED" -eq 1 ]]; then
echo "  3. Configura whitelist de dominios autorizados en el panel:"
echo "       https://${DOMAIN}/settings/mail"
echo
echo "  4. Verifica reputación de IP de correo:"
echo "       https://www.mail-tester.com"
echo "       bash scripts/dns_check.sh ${MAIL_DOMAIN:-tu-dominio.com} ${VPS_IP:-tu-ip}"
echo
fi
echo "  5. Logs en tiempo real:"
echo "       docker compose -f docker-compose.kos.yml logs -f"
echo
echo "  6. Prueba rápida del agente OpenClaw con OpenRouter:"
echo "       openclaw agent --message '¿Cuál es el modelo activo?' --thinking low"
echo
if [[ -n "${OR_FALLBACK:-}" ]]; then
echo "  7. Modelo principal: ${OR_MODEL}"
echo "     Fallback:         ${OR_FALLBACK}"
echo
fi

echo -e "${DIM}Archivos de configuración generados:${RESET}"
note "  ${ENV_FILE}   (600)"
note "  ${KOS_ENV_FILE}           (600)"
[[ -n "${OR_API_KEY:-}" ]] && note "  ${OPENCLAW_CONFIG}  (600)"
echo
