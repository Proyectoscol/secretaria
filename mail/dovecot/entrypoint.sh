#!/usr/bin/env bash
# mail/dovecot/entrypoint.sh — substitute ${MAIL_DOMAIN} before starting Dovecot.
# Dovecot does not perform shell variable expansion in config files; envsubst
# handles the SSL cert paths in 10-master.conf.
set -euo pipefail

MAIL_DOMAIN="${MAIL_DOMAIN:?MAIL_DOMAIN must be set}"

envsubst '${MAIL_DOMAIN}' \
  < /etc/dovecot/conf.d/10-master.conf.template \
  > /etc/dovecot/conf.d/10-master.conf

echo "[dovecot] Starting for domain: ${MAIL_DOMAIN}"
exec /usr/sbin/dovecot -F
