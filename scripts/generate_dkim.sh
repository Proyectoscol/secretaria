#!/usr/bin/env bash
# =============================================================================
# scripts/generate_dkim.sh — Genera par de claves DKIM para el dominio
# =============================================================================
# La clave privada va en el servidor (mail/opendkim/keys/).
# La clave pública va en DNS como registro TXT.
#
# Uso: bash scripts/generate_dkim.sh tu-dominio.com
#
# El selector utilizado es 'openclaw' — consistente con la configuración
# de OpenDKIM en mail/opendkim/opendkim.conf y con los registros DNS.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

DOMAIN="${1:-}"
SELECTOR="openclaw"

if [[ -z "$DOMAIN" ]]; then
  echo -e "${RED}Error: debes especificar el dominio.${RESET}"
  echo "  Uso: bash scripts/generate_dkim.sh tu-dominio.com"
  exit 1
fi

if ! command -v openssl &>/dev/null; then
  echo -e "${RED}Error: openssl no encontrado.${RESET}"
  echo "  Instalar: sudo apt-get install -y openssl"
  exit 1
fi

KEY_DIR="mail/opendkim/keys/${DOMAIN}"
PRIVATE_KEY="${KEY_DIR}/private.key"
PUBLIC_KEY="${KEY_DIR}/public.key"

# ─── Verificar si ya existen claves ──────────────────────────────────────────
if [[ -f "$PRIVATE_KEY" ]]; then
  echo -e "${YELLOW}[WARN]${RESET} Ya existen claves DKIM para ${DOMAIN} en ${KEY_DIR}"
  echo -n "  ¿Regenerar (esto invalida el registro DNS actual)? [s/N]: "
  read -r REGEN
  if [[ "${REGEN,,}" != "s" && "${REGEN,,}" != "si" ]]; then
    echo "  Usando claves existentes."
    SKIP_GEN=1
  else
    SKIP_GEN=0
  fi
else
  SKIP_GEN=0
fi

mkdir -p "${KEY_DIR}"
chmod 700 "${KEY_DIR}"

# ─── Generar claves ──────────────────────────────────────────────────────────
if [[ "$SKIP_GEN" -eq 0 ]]; then
  echo -e "${CYAN}[INFO]${RESET} Generando par de claves RSA 2048 para ${DOMAIN}…"
  openssl genrsa -out "${PRIVATE_KEY}" 2048 2>/dev/null
  openssl rsa -in "${PRIVATE_KEY}" -pubout -out "${PUBLIC_KEY}" 2>/dev/null
  chmod 600 "${PRIVATE_KEY}"
  chmod 644 "${PUBLIC_KEY}"
  echo -e "${GREEN}[ OK ]${RESET} Claves generadas"
fi

# ─── Extraer clave pública en formato DNS ────────────────────────────────────
# Eliminar encabezados PEM y newlines para formato TXT de DNS
PUBLIC_KEY_DNS=$(openssl rsa -in "${PRIVATE_KEY}" -pubout 2>/dev/null \
  | grep -v "PUBLIC KEY" \
  | tr -d '\n')

# ─── Salida para el operador ─────────────────────────────────────────────────
echo
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}${GREEN}  ✓ Claves DKIM generadas para ${DOMAIN}${RESET}"
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
echo -e "${BOLD}  Agrega este registro TXT en tu DNS:${RESET}"
echo
echo -e "  ${CYAN}Nombre:${RESET} ${SELECTOR}._domainkey.${DOMAIN}"
echo -e "  ${CYAN}Tipo:${RESET}   TXT"
echo -e "  ${CYAN}Valor:${RESET}  \"v=DKIM1; k=rsa; p=${PUBLIC_KEY_DNS}\""
echo
echo -e "${BOLD}  ━━━ Si la clave es muy larga, divídela así en Cloudflare/Route53: ━━━${RESET}"

# Dividir en fragmentos de 200 chars para compatibilidad con DNS
CHUNK_SIZE=200
KEY_LEN=${#PUBLIC_KEY_DNS}
CHUNK1="${PUBLIC_KEY_DNS:0:$CHUNK_SIZE}"
CHUNK2="${PUBLIC_KEY_DNS:$CHUNK_SIZE}"

if [[ ${KEY_LEN} -gt ${CHUNK_SIZE} ]]; then
  echo
  echo "  \"v=DKIM1; k=rsa; p=${CHUNK1}\""
  echo "  \"${CHUNK2}\""
fi

echo
echo -e "${BOLD}${YELLOW}  ━━━ Archivos generados: ━━━${RESET}"
echo "  Clave privada : ${PRIVATE_KEY}   ← NUNCA hacer commit"
echo "  Clave pública : ${PUBLIC_KEY}"
echo
echo -e "${RED}${BOLD}  ⚠ SEGURIDAD:${RESET}"
echo "  La clave privada (${PRIVATE_KEY}) NUNCA debe hacerse commit a Git."
echo "  Ya está en .gitignore. Verifica con: git status ${KEY_DIR}"
echo
echo -e "${BOLD}  ━━━ Verificar después de configurar DNS: ━━━${RESET}"
echo "  dig TXT ${SELECTOR}._domainkey.${DOMAIN}"
echo "  bash scripts/dns_check.sh ${DOMAIN} TU_IP_VPS"
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
