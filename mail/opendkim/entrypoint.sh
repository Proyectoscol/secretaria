#!/usr/bin/env bash
# mail/opendkim/entrypoint.sh — substitute ${MAIL_DOMAIN} before starting OpenDKIM
# OpenDKIM does not perform shell variable expansion; envsubst handles it here.
set -euo pipefail

MAIL_DOMAIN="${MAIL_DOMAIN:?MAIL_DOMAIN must be set}"

envsubst '${MAIL_DOMAIN}' \
  < /etc/opendkim.conf.template \
  > /etc/opendkim.conf

echo "[opendkim] Starting for domain: ${MAIL_DOMAIN}"
exec /usr/sbin/opendkim -f -x /etc/opendkim.conf
