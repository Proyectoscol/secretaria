#!/usr/bin/env bash
set -euo pipefail

MAIL_DOMAIN="${MAIL_DOMAIN:?MAIL_DOMAIN must be set}"

# Substitute domain in Postfix config
sed -i "s/\${MAIL_DOMAIN}/${MAIL_DOMAIN}/g" /etc/postfix/main.cf
sed -i "s/\${MAIL_DOMAIN}/${MAIL_DOMAIN}/g" /etc/postfix/virtual

# Generate virtual mailbox hash
postmap /etc/postfix/virtual
postmap /etc/postfix/header_checks

# Set hostname
postconf -e "myhostname = mail.${MAIL_DOMAIN}"
postconf -e "mydomain = ${MAIL_DOMAIN}"

# Update virtual_mailbox_domains
postconf -e "virtual_mailbox_domains = ${MAIL_DOMAIN}"

echo "[postfix] Starting with domain: ${MAIL_DOMAIN}"
exec /usr/sbin/postfix start-fg
