"""
agents/secretary/report_generator.py — HTML report and alert email generation.

Generates three report types:
  daily_summary    — document activity, recent queries, system status
  weekly_metrics   — trend analysis over the past 7 days
  monthly_analysis — month-over-month comparisons

Also generates alert emails for anomaly notifications.

Templates live in agents/secretary/templates/ and use inline CSS only
(Gmail and Outlook do not support external stylesheets or <style> blocks
in most email clients).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
DB_DSN = os.getenv("KOS_DB_DSN", "postgresql://openclaw:openclaw@postgres:5432/openclaw")

MAIL_SECRETARIO_DISPLAY_NAME = os.getenv("MAIL_SECRETARIO_DISPLAY_NAME", "Secretaria IA")
MAIL_DOMAIN = os.getenv("MAIL_DOMAIN", "")


def _get_db():
    return psycopg2.connect(DB_DSN)


class ReportGenerator:
    """Generates HTML reports and alert emails for the Secretary agent."""

    def _load_template(self, name: str) -> str:
        path = TEMPLATES_DIR / name
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            log.error("report_generator: template not found: %s", path)
            return "<p>Template not found.</p>"

    def _render(self, template: str, **kwargs) -> str:
        """Simple string-format substitution for template variables."""
        try:
            return template.format(**kwargs)
        except KeyError as exc:
            log.warning("report_generator: missing template variable: %s", exc)
            return template

    # ── Daily summary ─────────────────────────────────────────────────────────

    def generate_summary_report(
        self, tenant_id: str
    ) -> tuple[str, str]:
        """Return (html, plain_text) for the daily summary report."""
        db_conn = _get_db()
        try:
            stats = self._gather_daily_stats(tenant_id, db_conn)
        finally:
            db_conn.close()

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d de %B de %Y")

        base = self._load_template("base.html")
        content = self._load_template("report.html")

        rows_html = ""
        for key, label, value in stats:
            rows_html += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;color:#374151;">{label}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;font-weight:600;color:#111827;text-align:right;">{value}</td>
            </tr>"""

        body_html = self._render(
            content,
            report_title="Resumen Diario",
            report_date=date_str,
            stats_rows=rows_html,
            period_description="las últimas 24 horas",
        )

        full_html = self._render(
            base,
            display_name=MAIL_SECRETARIO_DISPLAY_NAME,
            content=body_html,
            year=now.year,
        )

        plain = f"Resumen Diario — {date_str}\n\n"
        for _, label, value in stats:
            plain += f"  {label}: {value}\n"
        plain += f"\n— {MAIL_SECRETARIO_DISPLAY_NAME}"

        return full_html, plain

    def _gather_daily_stats(self, tenant_id: str, db_conn) -> list[tuple]:
        """Query DB for daily activity statistics."""
        stats = []
        try:
            with db_conn.cursor() as cur:
                # Documents processed in last 24h
                cur.execute(
                    """
                    SELECT COUNT(*) FROM mail_messages
                    WHERE tenant_id = %s
                      AND received_at >= NOW() - INTERVAL '24 hours'
                      AND direction = 'inbound'
                    """,
                    (tenant_id,),
                )
                stats.append(("mail_inbound", "Correos recibidos (24h)", cur.fetchone()[0]))

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mail_outbound
                    WHERE tenant_id = %s
                      AND status = 'sent'
                      AND sent_at >= NOW() - INTERVAL '24 hours'
                    """,
                    (tenant_id,),
                )
                stats.append(("mail_outbound", "Correos enviados (24h)", cur.fetchone()[0]))

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mail_attachments ma
                    JOIN mail_messages mm ON ma.message_id = mm.id
                    WHERE mm.tenant_id = %s
                      AND ma.clamav_status = 'clean'
                      AND ma.created_at >= NOW() - INTERVAL '24 hours'
                    """,
                    (tenant_id,),
                )
                stats.append(("attachments_clean", "Adjuntos procesados (limpios)", cur.fetchone()[0]))

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mail_attachments ma
                    JOIN mail_messages mm ON ma.message_id = mm.id
                    WHERE mm.tenant_id = %s
                      AND ma.clamav_status = 'infected'
                      AND ma.created_at >= NOW() - INTERVAL '24 hours'
                    """,
                    (tenant_id,),
                )
                stats.append(("attachments_infected", "Adjuntos bloqueados (infectados)", cur.fetchone()[0]))

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mail_attachments ma
                    JOIN mail_messages mm ON ma.message_id = mm.id
                    WHERE mm.tenant_id = %s
                      AND ma.ingested = TRUE
                      AND ma.created_at >= NOW() - INTERVAL '24 hours'
                    """,
                    (tenant_id,),
                )
                stats.append(("docs_ingested", "Documentos ingestados en KOS", cur.fetchone()[0]))

        except Exception:
            log.exception("report_generator: error gathering daily stats for tenant %s", tenant_id)

        return stats

    # ── Weekly report ─────────────────────────────────────────────────────────

    def generate_weekly_report(self, tenant_id: str) -> tuple[str, str]:
        """Return (html, plain_text) for the weekly metrics report."""
        db_conn = _get_db()
        try:
            stats = self._gather_weekly_stats(tenant_id, db_conn)
        finally:
            db_conn.close()

        now = datetime.now(timezone.utc)
        date_str = now.strftime("Semana del %d de %B de %Y")

        base = self._load_template("base.html")
        content = self._load_template("report.html")

        rows_html = "".join(
            f"""<tr>
              <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;color:#374151;">{label}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;font-weight:600;color:#111827;text-align:right;">{value}</td>
            </tr>"""
            for _, label, value in stats
        )

        body_html = self._render(
            content,
            report_title="Métricas Semanales",
            report_date=date_str,
            stats_rows=rows_html,
            period_description="los últimos 7 días",
        )
        full_html = self._render(
            base,
            display_name=MAIL_SECRETARIO_DISPLAY_NAME,
            content=body_html,
            year=now.year,
        )

        plain = f"Métricas Semanales — {date_str}\n\n"
        for _, label, value in stats:
            plain += f"  {label}: {value}\n"
        plain += f"\n— {MAIL_SECRETARIO_DISPLAY_NAME}"

        return full_html, plain

    def _gather_weekly_stats(self, tenant_id: str, db_conn) -> list[tuple]:
        stats = []
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE direction = 'inbound'),
                        COUNT(*) FILTER (WHERE direction = 'outbound')
                    FROM mail_messages
                    WHERE tenant_id = %s
                      AND received_at >= NOW() - INTERVAL '7 days'
                    """,
                    (tenant_id,),
                )
                row = cur.fetchone()
                stats.append(("inbound_7d", "Correos recibidos (7 días)", row[0]))
                stats.append(("outbound_7d", "Correos enviados (7 días)", row[1]))

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mail_threads
                    WHERE tenant_id = %s
                      AND first_message_at >= NOW() - INTERVAL '7 days'
                    """,
                    (tenant_id,),
                )
                stats.append(("threads_7d", "Hilos de conversación nuevos", cur.fetchone()[0]))

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mail_attachments ma
                    JOIN mail_messages mm ON ma.message_id = mm.id
                    WHERE mm.tenant_id = %s
                      AND ma.ingested = TRUE
                      AND ma.created_at >= NOW() - INTERVAL '7 days'
                    """,
                    (tenant_id,),
                )
                stats.append(("docs_7d", "Documentos ingestados en KOS (7 días)", cur.fetchone()[0]))

        except Exception:
            log.exception("report_generator: error gathering weekly stats for tenant %s", tenant_id)
        return stats

    # ── Monthly report ────────────────────────────────────────────────────────

    def generate_monthly_report(self, tenant_id: str) -> tuple[str, str]:
        """
        Return (html, plain_text) for the monthly analysis report.

        Uses the LLM (heavy model) to generate a narrative analysis paragraph
        from the 30-day statistics. Falls back to a plain stat table if the
        LLM call fails.
        """
        db_conn = _get_db()
        try:
            stats = self._gather_weekly_stats(tenant_id, db_conn)
        finally:
            db_conn.close()

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%B %Y")

        # Build stats summary text for LLM input
        stats_text = "\n".join(f"  {label}: {value}" for _, label, value in stats)

        # Generate narrative with LLM (heavy model — runs inside Celery)
        narrative_html = self._generate_narrative(
            tenant_id=tenant_id,
            period=date_str,
            stats_text=stats_text,
        )

        rows_html = "".join(
            f"""<tr>
              <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;color:#374151;">{label}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;font-weight:600;color:#111827;text-align:right;">{value}</td>
            </tr>"""
            for _, label, value in stats
        )
        if narrative_html:
            rows_html += (
                f'<tr><td colspan="2" style="padding:12px;color:#374151;">'
                f"<strong>Análisis:</strong> {narrative_html}</td></tr>"
            )

        base = self._load_template("base.html")
        content = self._load_template("report.html")

        body_html = self._render(
            content,
            report_title=f"Análisis Mensual — {date_str}",
            report_date=date_str,
            stats_rows=rows_html,
            period_description=f"el mes de {date_str}",
        )
        full_html = self._render(
            base,
            display_name=MAIL_SECRETARIO_DISPLAY_NAME,
            content=body_html,
            year=now.year,
        )

        plain = f"Análisis Mensual — {date_str}\n\n{stats_text}\n\n— {MAIL_SECRETARIO_DISPLAY_NAME}"
        return full_html, plain

    def _generate_narrative(
        self, tenant_id: str, period: str, stats_text: str
    ) -> str:
        """
        Ask the LLM (heavy model) for a 2-3 sentence narrative analysis.

        Returns the narrative string (HTML-safe), or empty string on failure.
        LLM calls ONLY happen here — inside Celery tasks, never in request time.
        """
        try:
            from services.llm.client import llm_client  # noqa: PLC0415
            from services.llm.client import LLMAPIError, LLMMaxRetriesError  # noqa: PLC0415

            result = llm_client.complete(
                task="generate_report_monthly",
                tenant_id=tenant_id,
                system_prompt=(
                    "You are a business analyst writing concise email reports in Spanish. "
                    "Write 2-3 sentences of plain narrative analysis based on the statistics. "
                    "Be factual, use numbers, avoid filler. Output plain text, no markdown."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Período: {period}\n\nEstadísticas:\n{stats_text}\n\n"
                            "Escribe un análisis breve (2-3 oraciones)."
                        ),
                    }
                ],
                max_tokens=256,
                temperature=0.3,
            )
            # Escape for HTML safety
            import html as html_mod  # noqa: PLC0415
            return html_mod.escape(result["content"].strip())
        except Exception as exc:
            log.warning("report_generator: LLM narrative generation failed: %s", exc)
            return ""

    # ── Alert email ───────────────────────────────────────────────────────────

    def generate_alert_email(
        self, tenant_id: str, alert: dict
    ) -> tuple[str, str]:
        """Return (html, plain_text) for an anomaly alert email."""
        base = self._load_template("base.html")
        content = self._load_template("alert.html")

        change_pct = alert.get("change_pct", 0)
        direction = "⬆️ incrementó" if change_pct > 0 else "⬇️ cayó"
        color = "#dc2626" if change_pct < 0 else "#d97706"

        body_html = self._render(
            content,
            rule_name=alert.get("rule_name", "Anomalía detectada"),
            metric_key=alert.get("metric_key", ""),
            current_value=alert.get("current_value", "N/A"),
            previous_value=alert.get("previous_value", "N/A"),
            change_pct=abs(change_pct),
            direction=direction,
            alert_color=color,
            comparison_period=alert.get("comparison_period", "período anterior"),
        )
        now = datetime.now(timezone.utc)
        full_html = self._render(
            base,
            display_name=MAIL_SECRETARIO_DISPLAY_NAME,
            content=body_html,
            year=now.year,
        )

        plain = (
            f"ALERTA: {alert.get('rule_name')}\n\n"
            f"{alert.get('metric_key')} {direction} {abs(change_pct):.1f}%\n"
            f"Valor actual: {alert.get('current_value')}\n"
            f"Valor anterior: {alert.get('previous_value')}\n\n"
            f"— {MAIL_SECRETARIO_DISPLAY_NAME}"
        )

        return full_html, plain
