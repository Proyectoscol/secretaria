# Configuración DNS para el Sistema de Correo KOS

Configura estos registros **antes** de levantar Postfix/Dovecot.
Un sistema de correo con DNS mal configurado será rechazado por Gmail, Outlook y prácticamente todos los servidores modernos.

---

## Requisitos previos

| Requisito | Detalle |
|-----------|---------|
| Dominio propio | `empresa.com` |
| IP estática de la VPS | `1.2.3.4` |
| Acceso al panel DNS | Cloudflare, GoDaddy, Route53, etc. |
| Acceso al panel del proveedor de VPS | Para PTR / reverse DNS |
| **Puerto 25 abierto** | Muchos VPS lo bloquean por defecto — solicitar apertura |

---

## Apertura del puerto 25

> **Crítico**: sin el puerto 25 abierto en tu VPS, no puedes recibir correo.

La mayoría de proveedores bloquean el puerto 25 en instancias nuevas para combatir el spam.
Debes solicitarlo explícitamente:

- **Hetzner**: Panel → Proyectos → límites → solicitar apertura de puerto 25
- **DigitalOcean**: Enviar ticket de soporte mencionando que es para uso empresarial interno
- **OVH/Kimsufi**: Formulario de desbloqueo de puerto 25 en el panel de cliente
- **Vultr**: Panel → Account → API → puertos de correo (requiere cuenta verificada)
- **AWS EC2**: Panel EC2 → Network & Security → Security Groups → agregar regla entrante TCP 25

**Tiempo de respuesta**: normalmente 24-72 horas hábiles.

---

## Registros DNS a crear

Sustituye `empresa.com` por tu dominio e `1.2.3.4` por la IP de tu VPS.

### 1. Registro MX — Enruta el correo entrante

```
empresa.com.    300    IN    MX    10 mail.empresa.com.
```

Le dice al mundo: "el correo para @empresa.com llega al servidor `mail.empresa.com`".
La prioridad `10` es estándar (menor número = mayor prioridad).

### 2. Registro A — Resuelve el hostname del servidor

```
mail.empresa.com.    300    IN    A    1.2.3.4
```

Sin este registro, los servidores remotos no pueden encontrar tu IP.

### 3. Registro PTR — Reverse DNS (reputación crítica)

> ⚠️ **Este registro se configura en el panel de tu VPS, no en tu registrador de dominio.**

Ve al panel de tu proveedor de VPS → Red → IP → Reverse DNS / PTR y configura:

```
1.2.3.4   →   mail.empresa.com.
```

Sin PTR, tu IP aparece como anónima. Gmail y Outlook rechazarán o marcarán como spam todos tus correos.

**Verificar**: `dig -x 1.2.3.4 +short` debe devolver `mail.empresa.com.`

### 4. Registro SPF — Declara qué servidores pueden enviar

```
empresa.com.    300    IN    TXT    "v=spf1 mx a:mail.empresa.com ~all"
```

| Parte | Significado |
|-------|-------------|
| `v=spf1` | Versión de SPF |
| `mx` | El servidor en el registro MX puede enviar |
| `a:mail.empresa.com` | El A de mail puede enviar |
| `~all` | Softfail: otros servidores son sospechosos |

> Cuando estés seguro de que todo funciona, cambia `~all` a `-all` (hardfail).

### 5. Registro DKIM — Firma criptográfica

> La clave pública se genera con `bash scripts/generate_dkim.sh empresa.com`.
> El script imprime el registro TXT exacto que debes copiar.

```
openclaw._domainkey.empresa.com.    300    IN    TXT    "v=DKIM1; k=rsa; p=TU_CLAVE_PUBLICA_AQUI"
```

El selector `openclaw` es el nombre configurado en OpenDKIM. Debe ser consistente.

Si la clave es larga (>255 caracteres), muchos proveedores la dividen en dos cadenas entre comillas:
```
"v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA..." "continuación_de_la_clave=="
```

### 6. Registro DMARC — Política de autenticación

```
_dmarc.empresa.com.    300    IN    TXT    "v=DMARC1; p=quarantine; rua=mailto:dmarc@empresa.com; ruf=mailto:dmarc@empresa.com; fo=1; adkim=s; aspf=s; pct=100"
```

| Parámetro | Valor | Significado |
|-----------|-------|-------------|
| `p=quarantine` | política | Mover a spam si falla (usa `p=none` al inicio) |
| `rua=` | reportes agregados | Dónde recibir reportes de autenticación |
| `ruf=` | reportes forenses | Dónde recibir detalles de fallas |
| `fo=1` | fallo | Reportar si SPF o DKIM falla |
| `adkim=s` | strict | DKIM debe coincidir exactamente con el dominio |
| `aspf=s` | strict | SPF debe coincidir exactamente |
| `pct=100` | porcentaje | Aplicar a 100% de los correos |

**Progresión recomendada**:
1. Semana 1: `p=none` — solo monitoreo, sin acción
2. Semana 2-3: `p=quarantine` — sospechosos van a spam
3. Semana 4+: `p=reject` — rechazar fallas completamente

---

## Resumen completo de registros

```dns
; ── Correo entrante ──────────────────────────────────────────────────
empresa.com.                     MX    10 mail.empresa.com.

; ── Resolución del servidor ──────────────────────────────────────────
mail.empresa.com.                A        1.2.3.4

; ── Reverse DNS (en panel VPS, no aquí) ─────────────────────────────
; 4.3.2.1.in-addr.arpa.          PTR      mail.empresa.com.

; ── Autenticación ────────────────────────────────────────────────────
empresa.com.                     TXT      "v=spf1 mx a:mail.empresa.com ~all"
openclaw._domainkey.empresa.com. TXT      "v=DKIM1; k=rsa; p=CLAVE_PUBLICA"
_dmarc.empresa.com.              TXT      "v=DMARC1; p=quarantine; rua=mailto:dmarc@empresa.com; pct=100"
```

---

## Verificación

```bash
# Verificar todo de una vez:
bash scripts/dns_check.sh empresa.com 1.2.3.4

# Verificar MX
dig MX empresa.com

# Verificar SPF
dig TXT empresa.com | grep spf

# Verificar DKIM
dig TXT openclaw._domainkey.empresa.com

# Verificar DMARC
dig TXT _dmarc.empresa.com

# Verificar PTR
dig -x 1.2.3.4

# Verificar conectividad SMTP
telnet mail.empresa.com 25
```

---

## Tiempo de propagación

Los cambios DNS propagan en **15 minutos a 48 horas** dependiendo del TTL previo.
Usa `dig +short MX empresa.com @8.8.8.8` para consultar directamente Google DNS y ver el valor actual.

---

## Reputación de IP

> **Importante**: una IP nueva tarda **2-4 semanas** en ganar reputación.
> Los primeros correos pueden ir a spam incluso con DNS perfecto.

Herramientas de diagnóstico:
- **Mail Tester**: https://www.mail-tester.com — puntaje de entregabilidad (apunta a 10/10)
- **MXToolbox**: https://mxtoolbox.com/SuperTool.aspx — diagnóstico DNS completo
- **Google Postmaster**: https://postmaster.google.com — reputación ante Gmail
- **Spamhaus**: https://check.spamhaus.org — verificar blacklists

Si tu IP está en una blacklist:
1. **Spamhaus**: https://www.spamhaus.org/lookup/ → solicitar remoción
2. **Barracuda**: https://www.barracudacentral.org/rbl/removal-request
3. **SpamCop**: https://www.spamcop.net/bl.shtml

---

## Notas de seguridad

- Las claves DKIM (`mail/opendkim/keys/`) **nunca deben hacerse commit a Git**
- Están en `.gitignore` — verificar con `git status`
- Renovar claves DKIM cada 12 meses o tras cualquier compromiso
- El puerto 587 (submission) solo debe aceptar conexiones autenticadas desde dentro de la red Docker
- El puerto 25 es el único que se expone al exterior
