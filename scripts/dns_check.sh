#!/usr/bin/env bash
# =============================================================================
# scripts/dns_check.sh — Verificador automático de DNS para el sistema de correo
# =============================================================================
# Uso: bash scripts/dns_check.sh tu-dominio.com tu-ip-vps
#
# Verifica:
#   MX, A, PTR (reverse DNS), SPF, DKIM (selector openclaw), DMARC
#   Conectividad SMTP en puerto 25
#   Listas negras (Spamhaus, SpamCop)
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
fail() { echo -e "${RED}  ✗${RESET} $*"; ERRORS=$(( ERRORS + 1 )); }
warn() { echo -e "${YELLOW}  ⚠${RESET} $*"; WARNINGS=$(( WARNINGS + 1 )); }
info() { echo -e "${CYAN}  ·${RESET} $*"; }

DOMAIN="${1:-}"
VPS_IP="${2:-}"
ERRORS=0
WARNINGS=0

if [[ -z "$DOMAIN" || -z "$VPS_IP" ]]; then
  echo -e "${BOLD}Uso:${RESET} bash scripts/dns_check.sh tu-dominio.com tu-ip-vps"
  echo
  echo "  Ejemplo: bash scripts/dns_check.sh empresa.com 1.2.3.4"
  exit 1
fi

# ─── Verificar dependencia: dig ───────────────────────────────────────────────
if ! command -v dig &>/dev/null; then
  echo -e "${RED}Error: 'dig' no está instalado.${RESET}"
  echo "  Instalar: sudo apt-get install -y dnsutils"
  exit 1
fi

echo
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${CYAN}  Verificación DNS de correo para: ${DOMAIN}${RESET}"
echo -e "${BOLD}${CYAN}  IP esperada: ${VPS_IP}${RESET}"
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
echo

# ─── 1. Registro MX ──────────────────────────────────────────────────────────
echo -e "${BOLD}1. Registro MX${RESET}"
MX_RAW=$(dig +short MX "${DOMAIN}" 2>/dev/null || true)
if [[ -z "$MX_RAW" ]]; then
  fail "MX no encontrado para ${DOMAIN}"
  info "Agrega: ${DOMAIN}. MX 10 mail.${DOMAIN}."
elif echo "$MX_RAW" | grep -qi "mail\.${DOMAIN}"; then
  ok "MX → $(echo "$MX_RAW" | head -1)"
else
  warn "MX encontrado pero no apunta a mail.${DOMAIN}: $MX_RAW"
fi
echo

# ─── 2. Registro A para mail.domain ──────────────────────────────────────────
echo -e "${BOLD}2. Registro A (mail.${DOMAIN})${RESET}"
A_RECORD=$(dig +short A "mail.${DOMAIN}" 2>/dev/null || true)
if [[ "$A_RECORD" == "$VPS_IP" ]]; then
  ok "A (mail.${DOMAIN}) → ${A_RECORD}"
elif [[ -z "$A_RECORD" ]]; then
  fail "A no encontrado para mail.${DOMAIN}"
  info "Agrega: mail.${DOMAIN}. A ${VPS_IP}"
else
  fail "A apunta a ${A_RECORD}, esperado ${VPS_IP}"
fi
echo

# ─── 3. PTR — Reverse DNS ────────────────────────────────────────────────────
echo -e "${BOLD}3. Reverse DNS / PTR (${VPS_IP})${RESET}"
PTR=$(dig +short -x "${VPS_IP}" 2>/dev/null || true)
if echo "$PTR" | grep -qi "${DOMAIN}"; then
  ok "PTR → ${PTR}"
elif [[ -z "$PTR" ]]; then
  fail "PTR no configurado para ${VPS_IP}"
  info "Configúralo en el panel de tu proveedor de VPS (no en DNS):"
  info "  ${VPS_IP} → mail.${DOMAIN}"
else
  warn "PTR existe pero no coincide con ${DOMAIN}: ${PTR}"
fi
echo

# ─── 4. SPF ──────────────────────────────────────────────────────────────────
echo -e "${BOLD}4. Registro SPF${RESET}"
SPF=$(dig +short TXT "${DOMAIN}" 2>/dev/null | grep "v=spf1" | tr -d '"' || true)
if [[ -n "$SPF" ]]; then
  ok "SPF → ${SPF}"
  if echo "$SPF" | grep -q "\-all"; then
    ok "  Política SPF: -all (hardfail) ✓"
  elif echo "$SPF" | grep -q "~all"; then
    warn "  Política SPF: ~all (softfail) — considera -all cuando estés seguro"
  fi
else
  fail "SPF no encontrado"
  info "Agrega: ${DOMAIN}. TXT \"v=spf1 mx a:mail.${DOMAIN} ~all\""
fi
echo

# ─── 5. DKIM (selector openclaw) ─────────────────────────────────────────────
echo -e "${BOLD}5. Registro DKIM (selector: openclaw)${RESET}"
DKIM=$(dig +short TXT "openclaw._domainkey.${DOMAIN}" 2>/dev/null | tr -d '"' || true)
if echo "$DKIM" | grep -qi "v=DKIM1"; then
  ok "DKIM encontrado en openclaw._domainkey.${DOMAIN}"
  if echo "$DKIM" | grep -qi "k=rsa"; then
    ok "  Algoritmo: RSA ✓"
  fi
elif [[ -z "$DKIM" ]]; then
  fail "DKIM no encontrado en openclaw._domainkey.${DOMAIN}"
  info "Genera las claves con: bash scripts/generate_dkim.sh ${DOMAIN}"
  info "Luego agrega el registro TXT que imprime el script"
else
  warn "DKIM encontrado pero formato inesperado: ${DKIM}"
fi
echo

# ─── 6. DMARC ────────────────────────────────────────────────────────────────
echo -e "${BOLD}6. Registro DMARC${RESET}"
DMARC=$(dig +short TXT "_dmarc.${DOMAIN}" 2>/dev/null | tr -d '"' || true)
if echo "$DMARC" | grep -qi "v=DMARC1"; then
  ok "DMARC → ${DMARC}"
  if echo "$DMARC" | grep -qi "p=reject"; then
    ok "  Política DMARC: reject (máxima protección) ✓"
  elif echo "$DMARC" | grep -qi "p=quarantine"; then
    ok "  Política DMARC: quarantine ✓"
  elif echo "$DMARC" | grep -qi "p=none"; then
    warn "  Política DMARC: none (solo monitoreo) — OK para inicio"
  fi
elif [[ -z "$DMARC" ]]; then
  fail "DMARC no encontrado"
  info "Agrega: _dmarc.${DOMAIN}. TXT \"v=DMARC1; p=none; rua=mailto:dmarc@${DOMAIN}; pct=100\""
else
  warn "DMARC encontrado pero formato inesperado: ${DMARC}"
fi
echo

# ─── 7. Conectividad SMTP puerto 25 ──────────────────────────────────────────
echo -e "${BOLD}7. Conectividad SMTP (puerto 25)${RESET}"
if command -v nc &>/dev/null; then
  if nc -zw5 "${VPS_IP}" 25 2>/dev/null; then
    ok "Puerto 25 abierto en ${VPS_IP}"
  else
    fail "Puerto 25 cerrado o filtrado en ${VPS_IP}"
    info "Solicita la apertura al soporte de tu proveedor de VPS"
    info "Ver: docs/dns_setup.md sección 'Apertura del puerto 25'"
  fi
else
  warn "nc (netcat) no disponible — saltando verificación de puerto 25"
  info "Verifica manualmente: telnet ${VPS_IP} 25"
fi
echo

# ─── 8. Blacklists ───────────────────────────────────────────────────────────
echo -e "${BOLD}8. Listas negras (blacklists)${RESET}"
REVERSED=$(echo "${VPS_IP}" | awk -F. '{print $4"."$3"."$2"."$1}')

BLACKLISTS=(
  "zen.spamhaus.org"
  "bl.spamcop.net"
  "b.barracudacentral.org"
  "dnsbl.sorbs.net"
)

BL_CLEAN=1
for bl in "${BLACKLISTS[@]}"; do
  RESULT=$(dig +short "${REVERSED}.${bl}" 2>/dev/null || true)
  if [[ -z "$RESULT" ]]; then
    ok "No listado en ${bl}"
  else
    fail "LISTADO en ${bl} (respuesta: ${RESULT})"
    info "  → Solicitar remoción en: https://check.spamhaus.org/ o panel del proveedor"
    BL_CLEAN=0
  fi
done

if [[ "$BL_CLEAN" -eq 1 ]]; then
  ok "IP limpia en todas las blacklists verificadas"
fi
echo

# ─── Resumen ──────────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Resumen de verificación${RESET}"
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
echo

if [[ "$ERRORS" -eq 0 && "$WARNINGS" -eq 0 ]]; then
  echo -e "${GREEN}${BOLD}  ✓ Todo correcto. Tu DNS está listo para el sistema de correo.${RESET}"
elif [[ "$ERRORS" -eq 0 ]]; then
  echo -e "${YELLOW}${BOLD}  ⚠ ${WARNINGS} advertencia(s) — revisa los puntos marcados con ⚠${RESET}"
else
  echo -e "${RED}${BOLD}  ✗ ${ERRORS} error(es) críticos deben corregirse antes de continuar.${RESET}"
  if [[ "$WARNINGS" -gt 0 ]]; then
    echo -e "${YELLOW}    Además: ${WARNINGS} advertencia(s)${RESET}"
  fi
fi
echo
echo "  Guía completa: docs/dns_setup.md"
echo "  Verificación online: https://mxtoolbox.com/SuperTool.aspx"
echo "  Test de entregabilidad: https://www.mail-tester.com"
echo

[[ "$ERRORS" -gt 0 ]] && exit 1 || exit 0
