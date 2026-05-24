#!/usr/bin/env bash
# =============================================================================
# scripts/bootstrap.sh — KOS One-Command Bootstrap
# =============================================================================
# Installs all system dependencies, clones the repo, and launches the
# interactive onboarding wizard on a fresh Ubuntu 24 VPS.
#
# One-command usage (run as non-root user with sudo access):
#
#   curl -fsSL https://raw.githubusercontent.com/openclaw/openclaw/main/scripts/bootstrap.sh | bash
#
# Or with a specific branch:
#
#   curl -fsSL https://raw.githubusercontent.com/openclaw/openclaw/main/scripts/bootstrap.sh \
#     | BRANCH=my-branch bash
#
# =============================================================================

set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/openclaw/openclaw}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/kos}"

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[ OK ]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
die()     { echo -e "${RED}[FAIL]${RESET} $*" >&2; exit 1; }

# ─── Safety checks ────────────────────────────────────────────────────────────
[[ "$(id -u)" -eq 0 ]] && die "No ejecutes este script como root. Usa un usuario normal con sudo."

if ! grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
  warn "Este script fue probado en Ubuntu 24. Otras distribuciones pueden necesitar ajustes."
fi

# ─── Banner ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}"
cat <<'BANNER'
  ██╗  ██╗ ██████╗ ███████╗  Bootstrap
  ██║ ██╔╝██╔═══██╗██╔════╝  One-Command Install
  █████╔╝ ██║   ██║███████╗
  ██╔═██╗ ██║   ██║╚════██║  https://github.com/openclaw/openclaw
  ██║  ██╗╚██████╔╝███████║
  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
BANNER
echo -e "${RESET}"

# ─── Step 1: System dependencies ──────────────────────────────────────────────
info "Paso 1/4 — Instalando dependencias del sistema…"

sudo apt-get update -qq

# Docker
if ! command -v docker &>/dev/null; then
  info "Instalando Docker…"
  curl -fsSL https://get.docker.com | sudo bash
  sudo usermod -aG docker "$USER"
  DOCKER_NEWLY_INSTALLED=1
else
  success "Docker ya instalado: $(docker --version)"
  DOCKER_NEWLY_INSTALLED=0
fi

# Docker Compose V2 plugin
if ! docker compose version &>/dev/null 2>&1; then
  info "Instalando Docker Compose V2…"
  sudo apt-get install -y docker-compose-v2
fi

# Other tools
sudo apt-get install -y --no-install-recommends \
  nginx \
  certbot \
  python3-certbot-nginx \
  curl \
  git \
  openssl \
  jq

sudo systemctl enable --now docker nginx

success "Dependencias instaladas"

# ─── Step 2: Clone repo ────────────────────────────────────────────────────────
info "Paso 2/4 — Clonando repositorio en ${INSTALL_DIR}…"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
  info "Repositorio ya existe — actualizando a rama ${BRANCH}…"
  cd "$INSTALL_DIR"
  git fetch origin
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
else
  sudo mkdir -p "$(dirname "$INSTALL_DIR")"
  sudo chown "$USER:$USER" "$(dirname "$INSTALL_DIR")"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi
success "Repositorio listo en ${INSTALL_DIR}"

# ─── Step 3: Verify scripts ────────────────────────────────────────────────────
info "Paso 3/4 — Verificando scripts de onboarding…"

ONBOARDING_SCRIPT="${INSTALL_DIR}/scripts/onboarding.sh"
if [[ ! -f "$ONBOARDING_SCRIPT" ]]; then
  die "No se encontró scripts/onboarding.sh en ${INSTALL_DIR}. Verifica el repositorio."
fi
chmod +x "$ONBOARDING_SCRIPT"
success "Script de onboarding verificado"

# ─── Step 4: Hand off to onboarding ───────────────────────────────────────────
info "Paso 4/4 — Lanzando onboarding interactivo…"
echo

if [[ "${DOCKER_NEWLY_INSTALLED:-0}" -eq 1 ]]; then
  warn "Docker fue instalado en esta sesión."
  warn "Para aplicar los permisos de grupo Docker, el script de onboarding"
  warn "se ejecutará a través de 'sg docker' (equivale a cerrar y abrir sesión)."
  echo
  exec sg docker -c "REPO_DIR='${INSTALL_DIR}' bash '${ONBOARDING_SCRIPT}'"
else
  exec REPO_DIR="${INSTALL_DIR}" bash "$ONBOARDING_SCRIPT"
fi
