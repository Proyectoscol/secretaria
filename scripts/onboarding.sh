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
#  12  Final health-check & summary
# =============================================================================

set -euo pipefail

# ─── Colours ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[ OK ]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ ERR]${RESET} $*"; }
header()  { echo -e "\n${BOLD}${CYAN}═══ $* ═══${RESET}\n"; }
note()    { echo -e "${DIM}      $*${RESET}"; }

confirm() {
  local prompt="${1:-Continuar?}"
  local answer
  while true; do
    read -rp "$(echo -e "${YELLOW}  ${prompt} [s/N]: ${RESET}")" answer
    case "${answer,,}" in
      s|si|sí|y|yes) return 0 ;;
      n|no|"")        return 1 ;;
      *) echo "  Escribe 's' para sí o 'n' para no." ;;
    esac
  done
}

prompt() {
  # Usage: VAR=$(prompt VAR_NAME "Prompt text" "default")
  local _var="$1" prompt_text="$2" default="${3:-}"
  local value
  if [[ -n "$default" ]]; then
    read -rp "$(echo -e "${CYAN}  ${prompt_text} [${default}]: ${RESET}")" value
    echo "${value:-$default}"
  else
    while true; do
      read -rp "$(echo -e "${CYAN}  ${prompt_text}: ${RESET}")" value
      [[ -n "$value" ]] && break
      warn "Este campo es obligatorio."
    done
    echo "$value"
  fi
}

prompt_optional() {
  local prompt_text="$1" default="${2:-}"
  local value
  read -rp "$(echo -e "${CYAN}  ${prompt_text} [${default:-(dejar vacío)}]: ${RESET}")" value
  echo "${value:-$default}"
}

prompt_secret() {
  local prompt_text="$1"
  local value confirm_value
  while true; do
    read -rsp "$(echo -e "${CYAN}  ${prompt_text}: ${RESET}")" value; echo
    read -rsp "$(echo -e "${CYAN}  Confirmar: ${RESET}")" confirm_value; echo
    [[ "$value" == "$confirm_value" ]] && break
    warn "Los valores no coinciden. Intenta nuevamente."
  done
  echo "$value"
}

prompt_secret_optional() {
  local prompt_text="$1"
  local value
  read -rsp "$(echo -e "${CYAN}  ${prompt_text} (Enter para omitir): ${RESET}")" value; echo
  echo "$value"
}

pick_one() {
  # pick_one "Prompt" "opt1" "opt2" "opt3" …  → returns chosen value
  local prompt_text="$1"; shift
  local options=("$@")
  local i=1
  echo -e "${CYAN}  ${prompt_text}${RESET}"
  for opt in "${options[@]}"; do
    echo -e "    ${BOLD}$i)${RESET} $opt"
    (( i++ ))
  done
  while true; do
    read -rp "$(echo -e "${YELLOW}  Elige [1-${#options[@]}]: ${RESET}")" choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
      echo "${options[$(( choice - 1 ))]}"
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
# SECCIÓN 1/12 — Prerequisitos del sistema
# =============================================================================
header "1/12 — Verificando prerequisitos del sistema"

check_cmd() {
  if command -v "$1" &>/dev/null; then
    success "$1 encontrado ($(command -v "$1"))"
    return 0
  else
    error "$1 no encontrado"
    return 1
  fi
}

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
# SECCIÓN 2/12 — Repositorio
# =============================================================================
header "2/12 — Repositorio"

if [[ -f "${REPO_DIR}/docker-compose.kos.yml" ]]; then
  success "Repositorio encontrado en: ${REPO_DIR}"
else
  info "No se encontró el repositorio en el directorio actual."
  CLONE_DIR=$(prompt CLONE_DIR "Directorio de destino" "/opt/kos")
  REPO_URL=$(prompt REPO_URL "URL del repositorio Git" "https://github.com/openclaw/openclaw")
  git clone "$REPO_URL" "$CLONE_DIR"
  REPO_DIR="$CLONE_DIR"
  success "Repositorio clonado en $REPO_DIR"
fi
cd "$REPO_DIR"

# =============================================================================
# SECCIÓN 3/12 — Variables de entorno
# =============================================================================
header "3/12 — Variables de entorno (KOS + frontend)"

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
EOF
chmod 600 "$KOS_ENV_FILE"
success ".env.kos creado"

# =============================================================================
# SECCIÓN 4/12 — OpenRouter (gestión de modelos y tokens)
# =============================================================================
header "4/12 — OpenRouter — Gestión de modelos de IA"

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
# SECCIÓN 5/12 — Langfuse (observabilidad y trazas de LLM)
# =============================================================================
header "5/12 — Langfuse — Observabilidad de LLM"

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

  cat > "$OPENCLAW_CONFIG" <<EOF
{
  "env": {
    "OPENROUTER_API_KEY": "${OR_API_KEY}"${LF_ENV_BLOCK}
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "${OR_MODEL}"${FALLBACK_BLOCK}
      },
      "models": {
        "${OR_MODEL}": {}${FALLBACK_MODEL_ENTRY}
      }
    }
  }
}
EOF
  chmod 600 "$OPENCLAW_CONFIG"
  success "~/.openclaw/openclaw.json escrito (permisos 600)"

  # Quick format validation
  if command -v jq &>/dev/null; then
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
# SECCIÓN 6/12 — Servicios de infraestructura (Redis, ClamAV, GROBID)
# =============================================================================
header "6/12 — Servicios de infraestructura"

info "Levantando Redis, ClamAV, GROBID…"
info "Primera vez: ClamAV descarga ~200 MB de definiciones de virus. Ten paciencia."

docker compose -f docker-compose.kos.yml up -d redis clamav grobid

info "Esperando a que Redis esté disponible…"
REDIS_READY=0
for i in $(seq 1 30); do
  if docker compose -f docker-compose.kos.yml exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
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
  if docker compose -f docker-compose.kos.yml exec -T clamav clamdscan --ping 3 &>/dev/null; then
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
# SECCIÓN 7/12 — pgweb (inspector de BD opcional)
# =============================================================================
header "7/12 — Inspector de base de datos (opcional)"

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
# SECCIÓN 8/12 — Migraciones de base de datos
# =============================================================================
header "8/12 — Migraciones de base de datos"

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
# SECCIÓN 9/12 — Build y migraciones de Prisma (Next.js)
# =============================================================================
header "9/12 — Build del frontend (Prisma + Next.js)"

info "Construyendo imagen Docker del frontend…"
info "Primera vez: puede tardar 5-10 minutos (descarga node:20-alpine, npm install)."

docker build \
  -t kos-frontend:latest \
  -f "${REPO_DIR}/frontend/Dockerfile.frontend" \
  "${REPO_DIR}/frontend"
success "Imagen kos-frontend:latest construida"

info "Aplicando migraciones Prisma…"
docker run --rm --net=host \
  --env-file "$ENV_FILE" \
  kos-frontend:latest \
  npx prisma migrate deploy 2>/dev/null || \
docker run --rm --net=host \
  --env-file "$ENV_FILE" \
  kos-frontend:latest \
  npx prisma db push --skip-generate
success "Migraciones Prisma aplicadas"

# =============================================================================
# SECCIÓN 10/12 — Todos los servicios KOS
# =============================================================================
header "10/12 — Iniciando todos los servicios KOS"

info "Construyendo imagen Python (Dockerfile.kos)…"
info "Primera vez: descarga sentence-transformers (~400 MB). Sé paciente."
docker build \
  -t kos-python:latest \
  -f "${REPO_DIR}/Dockerfile.kos" \
  "${REPO_DIR}"
success "Imagen kos-python:latest construida"

info "Levantando celery_worker, librarian_api y frontend…"
docker compose -f docker-compose.kos.yml up -d celery_worker librarian_api frontend
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
  error "Revisa: docker compose -f docker-compose.kos.yml logs librarian_api"
  exit 1
fi
success "Librarian API OK"

info "Esperando al frontend Next.js (puerto 3000)…"
for i in $(seq 1 30); do
  curl -sf "http://localhost:3000" &>/dev/null && break
  sleep 3
done

# =============================================================================
# SECCIÓN 11/12 — Nginx + SSL
# =============================================================================
header "11/12 — Nginx + SSL (Let's Encrypt)"

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
    MAIL_PASS=$(prompt_secret "Contraseña del buzón")
    MAIL_DISPLAY=$(prompt_optional "Nombre del Secretario" "Secretaria IA")

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
MAIL_RECEIVE_MODE=imap
MAIL_POLL_INTERVAL_SECONDS=30
MAIL_MAX_DAILY_OUTBOUND=500
MAIL_REPORT_TIMEZONE=America/Bogota
MAIL_SMTP_HOST=postfix
MAIL_SMTP_PORT=587
MAIL_IMAP_HOST=dovecot
MAIL_IMAP_PORT=993
MAILENV
    chmod 600 "$KOS_ENV_FILE"
    success "Variables de correo guardadas en .env.kos"

    # ── 7. Aplicar migración de correo ────────────────────────────────────
    echo
    if confirm "¿Aplicar migración de base de datos para el sistema de correo? (003_mail_schema.sql)"; then
      DB_PASS=$(echo "$KOS_DB_DSN" | grep -oP '(?<=:)[^:@]+(?=@)' || true)
      if docker run --rm --net=host \
          -e PGPASSWORD="${DB_PASS}" \
          -v "${REPO_DIR}/migrations:/migrations:ro" \
          postgres:16-alpine \
          psql "$KOS_DB_DSN" -f "/migrations/003_mail_schema.sql"; then
        success "003_mail_schema.sql aplicado"
      else
        error "Error aplicando migración de correo"
        warn "Puedes aplicarla manualmente: psql \$KOS_DB_DSN < migrations/003_mail_schema.sql"
      fi
    fi

    # ── 8. Levantar servicios de correo ───────────────────────────────────
    echo
    info "Construyendo y levantando servicios de correo…"
    info "(Primera vez: puede tardar 2-3 minutos)"
    docker compose -f "${REPO_DIR}/docker-compose.kos.yml" up -d \
      postfix dovecot opendkim rspamd celery_beat

    # Health check
    sleep 10
    if docker compose -f "${REPO_DIR}/docker-compose.kos.yml" ps postfix 2>/dev/null \
        | grep -q "Up\|running"; then
      success "Postfix activo"
    else
      warn "Postfix no confirmado — revisa: docker compose logs postfix"
    fi

    if docker compose -f "${REPO_DIR}/docker-compose.kos.yml" ps dovecot 2>/dev/null \
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

if curl -sf "https://${DOMAIN}" &>/dev/null; then
  success "✓ Frontend HTTPS: https://${DOMAIN}"
else
  warn "  Frontend HTTPS no responde aún (puede necesitar unos segundos)"
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
  printf "║  Frontend:      https://%-36s║\n" "${DOMAIN}"
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
