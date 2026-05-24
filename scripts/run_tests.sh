#!/usr/bin/env bash
# scripts/run_tests.sh — KOS test runner (ordered by criticality)
#
# Usage:
#   ./scripts/run_tests.sh           # all fast tests (default)
#   ./scripts/run_tests.sh fast      # same — must complete < 2min on the VPS
#   ./scripts/run_tests.sh full      # fast + integration (needs DATABASE_URL)
#   ./scripts/run_tests.sh security  # security tests only (Stage 0)
#   ./scripts/run_tests.sh unit      # unit tests only (Stages 1-4)
#
# Exit codes:
#   0 — all tests passed
#   1 — one or more tests failed
#   2 — setup/dependency error
#
# IMPORTANT: Stage 0 (security) always runs and aborts the suite on failure.
# Never deploy if Stage 0 fails.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-fast}"
PASS=0
FAIL=0
START_TIME=$(date +%s)

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────

print_stage() {
  echo ""
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BLUE}  Stage $1: $2${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

run_pytest() {
  local label="$1"
  shift
  echo -e "\n${YELLOW}→ Running: $label${NC}"
  if python -m pytest "$@"; then
    PASS=$((PASS + 1))
    echo -e "${GREEN}  ✓ PASSED: $label${NC}"
  else
    FAIL=$((FAIL + 1))
    echo -e "${RED}  ✗ FAILED: $label${NC}"
  fi
}

# Like run_pytest but aborts the whole suite on failure (used for security tests)
run_pytest_critical() {
  local label="$1"
  shift
  echo -e "\n${YELLOW}→ Running (CRITICAL): $label${NC}"
  if python -m pytest "$@"; then
    PASS=$((PASS + 1))
    echo -e "${GREEN}  ✓ PASSED: $label${NC}"
  else
    echo ""
    echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}${BOLD}║  SECURITY TEST FAILED — ABORTING SUITE                       ║${NC}"
    echo -e "${RED}${BOLD}║  DO NOT DEPLOY until this is fixed.                          ║${NC}"
    echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    exit 1
  fi
}

check_dependency() {
  local pkg="$1"
  python -c "import $pkg" 2>/dev/null || {
    echo -e "${RED}ERROR: Python package '$pkg' not installed.${NC}"
    echo "Run: pip install -r requirements.kos.txt"
    exit 2
  }
}

_print_summary() {
  END_TIME=$(date +%s)
  ELAPSED=$((END_TIME - START_TIME))
  echo ""
  echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
  echo -e "${BLUE}  TEST SUMMARY${NC}"
  echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
  echo -e "  Mode:    ${MODE}"
  echo -e "  Elapsed: ${ELAPSED}s"
  echo -e "  Passed:  ${GREEN}${PASS}${NC}"
  echo -e "  Failed:  ${RED}${FAIL}${NC}"
  if [[ $FAIL -eq 0 ]]; then
    echo -e "\n  ${GREEN}All tests passed ✓${NC}"
  else
    echo -e "\n  ${RED}${FAIL} suite(s) failed ✗${NC}"
  fi
  echo ""
}

# ── Dependency check ──────────────────────────────────────────────────────────

echo -e "${BLUE}${BOLD}KOS Test Suite — mode: ${MODE}${NC}"
echo "Root: $REPO_ROOT"

check_dependency pytest
check_dependency psycopg2
check_dependency httpx

# ── STAGE 0: Security tests ───────────────────────────────────────────────────
# Always runs first. Aborts the entire suite on failure.
# Never skip this stage. Never deploy if it fails.

print_stage 0 "TOKEN ISOLATION & SECURITY (abort on failure)"
run_pytest_critical "token isolation" \
  tests/security/test_token_isolation.py \
  -m "not integration"

if [[ "$MODE" == "security" ]]; then
  _print_summary
  exit 0
fi

# ── Stage 1: Env validation ───────────────────────────────────────────────────

print_stage 1 "Configuration & Env Validation"
run_pytest "env_validator tests" \
  tests/config/test_env_validator.py \
  -m "not integration"

# ── Stage 2: Mail security ────────────────────────────────────────────────────

print_stage 2 "Mail Security (ClamAV, whitelist, no-bounce, limits)"
run_pytest "mail security" \
  tests/mail/test_mail_security.py \
  -m "not integration"

# ── Stage 3: Unit tests ───────────────────────────────────────────────────────

print_stage 3 "Unit Tests (parser, whitelist, thread builder, LLM client)"
run_pytest "mail parser"        tests/mail/test_parser.py        -m "not integration"
run_pytest "mail whitelist"     tests/mail/test_whitelist.py     -m "not integration"
run_pytest "mail thread builder" tests/mail/test_thread_builder.py -m "not integration"
run_pytest "LLM client"         tests/llm/test_llm_client.py     -m "not integration"

if [[ "$MODE" == "unit" ]]; then
  _print_summary
  exit $([[ $FAIL -eq 0 ]] && echo 0 || echo 1)
fi

# ── Stage 4: KOS core ─────────────────────────────────────────────────────────

print_stage 4 "KOS Core Tests (multitenancy, ingestion, librarian)"
run_pytest "kos core" \
  tests/kos/ \
  -m "not integration"

# ── Stage 5: Integration (optional) ──────────────────────────────────────────

if [[ "$MODE" == "full" ]]; then
  print_stage 5 "Integration Tests (requires DATABASE_URL)"
  if [[ -z "${DATABASE_URL:-}" && -z "${KOS_DB_DSN:-}" ]]; then
    echo -e "${YELLOW}  ⚠ DATABASE_URL not set — skipping integration tests${NC}"
  else
    run_pytest "ingest to retrieve" \
      tests/integration/test_ingest_to_retrieve.py \
      -m "integration"
    run_pytest "mail to classify" \
      tests/integration/test_mail_to_classify.py \
      -m "integration"
  fi
fi

_print_summary

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
