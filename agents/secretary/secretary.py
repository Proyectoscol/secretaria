"""
agents/secretary/secretary.py — Secretario IA — core agent logic.

The Secretary is a read/write agent that:
1. Monitors and classifies authorized inbound emails
2. Generates responses when appropriate
3. Sends scheduled reports and proactive alerts
4. Consults the Librarian for document-enriched analysis
5. Never writes to external systems — only email and internal DB

Inbound lifecycle:
  Received → Authorized → Parsed → Classified → Responded / Archived

Outbound lifecycle:
  Trigger (schedule / anomaly / reply) → Generate → Send → Log

Classification types:
  'report_request'       — someone asks for a report → generate and reply
  'query'                — question about data → consult Librarian + sources
  'alert_acknowledgment' — acknowledgment of a previous alert → archive
  'reply'                — reply to something we sent → save context
  'informational'        — FYI, no action required → archive
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Optional

import psycopg2

log = logging.getLogger(__name__)

DB_DSN: str = os.getenv(
    "KOS_DB_DSN",
    "postgresql://openclaw:openclaw@postgres:5432/openclaw",
)
LIBRARIAN_API_URL: str = os.getenv("LIBRARIAN_API_URL", "http://librarian_api:8001")
MAIL_SECRETARIO_ADDRESS: str = os.getenv("MAIL_SECRETARIO_ADDRESS", "")
MAIL_SECRETARIO_DISPLAY_NAME: str = os.getenv(
    "MAIL_SECRETARIO_DISPLAY_NAME", "Secretaria IA"
)


def _get_db():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    return conn


class SecretaryAgent:
    """
    Core Secretary IA agent.

    Stateless between calls — all state lives in PostgreSQL.
    One instance can be shared across threads (no instance variables modified).
    """

    # ── Inbound message processing ────────────────────────────────────────────

    def process_inbound_message(
        self, message_uuid: str, tenant_id: str
    ) -> dict:
        """
        Classify and act on an authorized inbound message.

        Reads the message from DB, classifies its intent, and takes action:
        - report_request → generate report, reply
        - query → consult Librarian, reply with enriched answer
        - alert_acknowledgment → update outbound record, archive
        - reply → archive with context note
        - informational → archive

        Updates ai_classification, ai_priority, ai_action_taken in DB.
        """
        db_conn = _get_db()
        try:
            # Load message
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT subject, body_text, body_html, from_address,
                           from_name, message_id, thread_id
                    FROM mail_messages
                    WHERE id = %s AND tenant_id = %s
                    """,
                    (message_uuid, tenant_id),
                )
                row = cur.fetchone()

            if not row:
                log.warning(
                    "secretary: message %s not found for tenant %s",
                    message_uuid,
                    tenant_id,
                )
                return {"status": "not_found"}

            subject, body_text, body_html, from_address, from_name, rfc_message_id, thread_id = row
            body = body_text or ""

            # Classify intent via LLM (light model), with heuristic fallback
            classification = self._classify_intent(subject, body, tenant_id)
            priority = self._assess_priority(subject, body, classification)

            action_taken = "archived"

            if classification == "report_request":
                action_taken = self._handle_report_request(
                    message_uuid, tenant_id, subject, body,
                    from_address, rfc_message_id, db_conn
                )
            elif classification == "query":
                action_taken = self._handle_query(
                    message_uuid, tenant_id, subject, body,
                    from_address, rfc_message_id, db_conn
                )
            elif classification == "alert_acknowledgment":
                action_taken = "alert_acknowledged"
            elif classification == "reply":
                action_taken = "reply_logged"
            else:
                action_taken = "archived_informational"

            # Update AI fields in DB
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mail_messages
                    SET ai_classification = %s,
                        ai_priority       = %s,
                        ai_action_taken   = %s,
                        processing_status = 'processed',
                        processed_at      = NOW()
                    WHERE id = %s AND tenant_id = %s
                    """,
                    (classification, priority, action_taken, message_uuid, tenant_id),
                )
            db_conn.commit()

            log.info(
                "secretary: processed message %s — classification=%s action=%s",
                message_uuid,
                classification,
                action_taken,
            )
            return {
                "status": "ok",
                "classification": classification,
                "action": action_taken,
            }

        except Exception:
            db_conn.rollback()
            log.exception(
                "secretary: error processing message %s for tenant %s",
                message_uuid,
                tenant_id,
            )
            return {"status": "error"}
        finally:
            db_conn.close()

    def _classify_intent(
        self, subject: str, body: str, tenant_id: str = ""
    ) -> str:
        """
        LLM-based intent classifier via OpenRouter (light model: gpt-4o-mini).

        Falls back to keyword heuristics if the LLM call fails so the pipeline
        never stalls on an API outage.

        Classification categories:
          report_request       — user is asking for a report
          query                — question about data / documents
          alert_acknowledgment — acknowledging a previous alert
          reply                — reply to something we sent
          informational        — FYI, no action required
        """
        try:
            from services.llm.client import llm_client  # noqa: PLC0415
            from services.llm.client import LLMAPIError, LLMMaxRetriesError  # noqa: PLC0415

            # Truncate to avoid large token usage for classification
            snippet_subject = subject[:200]
            snippet_body = body[:800]

            result = llm_client.complete(
                task="classify_email",
                tenant_id=tenant_id,
                system_prompt=(
                    "You are an email intent classifier for a legal/business secretary AI. "
                    "Respond with EXACTLY ONE of these labels (no explanation, no punctuation):\n"
                    "  report_request\n"
                    "  query\n"
                    "  alert_acknowledgment\n"
                    "  reply\n"
                    "  informational\n\n"
                    "Rules:\n"
                    "- report_request: sender explicitly asks to generate or send a report.\n"
                    "- query: sender asks a question about data, documents, or system status.\n"
                    "- alert_acknowledgment: short acknowledgment of a previous alert (≤3 sentences).\n"
                    "- reply: reply to an email we sent (subject starts with Re: or Fwd:).\n"
                    "- informational: none of the above.\n"
                    "Default to informational when uncertain."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Subject: {snippet_subject}\n\n"
                            f"Body (first 800 chars):\n{snippet_body}"
                        ),
                    }
                ],
                max_tokens=10,
                temperature=0.0,
            )
            label = result["content"].strip().lower().split()[0]
            valid = {"report_request", "query", "alert_acknowledgment", "reply", "informational"}
            if label in valid:
                log.debug(
                    "secretary: LLM classified intent=%s (model=%s)",
                    label,
                    result.get("model"),
                )
                return label
            log.warning(
                "secretary: LLM returned unknown label %r — falling back to heuristics",
                label,
            )
        except (LLMAPIError, LLMMaxRetriesError) as exc:
            log.warning(
                "secretary: LLM classification failed (%s) — falling back to heuristics",
                exc,
            )
        except Exception as exc:
            log.warning(
                "secretary: unexpected LLM error (%s) — falling back to heuristics",
                exc,
            )

        return self._classify_intent_heuristic(subject, body)

    def _classify_intent_heuristic(self, subject: str, body: str) -> str:
        """Keyword-based fallback classifier (no external calls)."""
        text = (subject + " " + body).lower()
        subject_lower = subject.lower()

        report_keywords = [
            "reporte", "report", "informe", "resumen", "estadísticas",
            "métricas", "análisis", "generar reporte", "enviar reporte",
            "necesito el reporte", "puedes enviar", "por favor envía",
        ]
        query_keywords = [
            "qué dice", "cuánto", "cuántos", "cuántas", "cómo está",
            "cuál es", "busca", "buscar", "encuentra", "información sobre",
            "datos de", "detalles de", "estado de", "how many", "what is",
            "find", "search", "query",
        ]
        ack_keywords = [
            "recibido", "entendido", "ok", "gracias", "confirmado",
            "acknowledged", "received", "noted", "thanks",
        ]

        if any(kw in text for kw in report_keywords):
            return "report_request"
        if any(kw in text for kw in query_keywords):
            return "query"
        if len(text) < 200 and any(kw in text for kw in ack_keywords):
            return "alert_acknowledgment"
        if "re:" in subject_lower or "fw:" in subject_lower or "fwd:" in subject_lower:
            return "reply"
        return "informational"

    def _assess_priority(self, subject: str, body: str, classification: str) -> str:
        """Heuristic priority assessment."""
        text = (subject + " " + body).lower()
        high_keywords = ["urgente", "urgent", "crítico", "critical", "alerta", "alert", "error"]
        low_keywords = ["fyi", "info", "informativo", "newsletter"]

        if any(kw in text for kw in high_keywords):
            return "high"
        if any(kw in text for kw in low_keywords):
            return "low"
        if classification == "report_request":
            return "medium"
        return "low"

    # ── Report request handler ────────────────────────────────────────────────

    def _handle_report_request(
        self,
        message_uuid: str,
        tenant_id: str,
        subject: str,
        body: str,
        from_address: str,
        in_reply_to_id: str,
        db_conn,
    ) -> str:
        """Generate a quick report and reply to the requester."""
        try:
            from agents.secretary.report_generator import ReportGenerator  # noqa: PLC0415
            from services.mail.sender import send_mail  # noqa: PLC0415

            generator = ReportGenerator()
            report_html, report_text = generator.generate_summary_report(tenant_id)

            result = send_mail(
                from_address=MAIL_SECRETARIO_ADDRESS,
                to_addresses=[from_address],
                subject=f"Re: {subject}",
                body_html=report_html,
                body_text=report_text,
                in_reply_to=in_reply_to_id,
                tenant_id=tenant_id,
                trigger_type="reply",
                trigger_detail={"inbound_message_id": message_uuid},
                db_conn=db_conn,
            )
            if result["success"]:
                return "report_generated_and_sent"
            return f"report_send_failed: {result.get('error')}"
        except Exception:
            log.exception("secretary: _handle_report_request failed")
            return "report_request_error"

    # ── Query handler ─────────────────────────────────────────────────────────

    def _handle_query(
        self,
        message_uuid: str,
        tenant_id: str,
        subject: str,
        body: str,
        from_address: str,
        in_reply_to_id: str,
        db_conn,
    ) -> str:
        """Consult the Librarian and reply with enriched answer."""
        try:
            from services.mail.sender import send_mail  # noqa: PLC0415

            # Consult Librarian for document context
            librarian_response = self._consult_librarian(body or subject, tenant_id)

            answer_html = f"""
            <p>Hola,</p>
            <p>Aquí tienes la información solicitada:</p>
            <blockquote style="border-left: 3px solid #f59e0b; padding-left: 1em; color: #555;">
              {librarian_response or "No encontré documentos relevantes para tu consulta."}
            </blockquote>
            <p>Si necesitas más detalles, puedes responder a este correo.</p>
            """

            result = send_mail(
                from_address=MAIL_SECRETARIO_ADDRESS,
                to_addresses=[from_address],
                subject=f"Re: {subject}",
                body_html=answer_html,
                body_text=librarian_response,
                in_reply_to=in_reply_to_id,
                tenant_id=tenant_id,
                trigger_type="reply",
                trigger_detail={
                    "inbound_message_id": message_uuid,
                    "query_type": "librarian",
                },
                db_conn=db_conn,
            )
            return "query_answered_sent" if result["success"] else "query_answer_send_failed"
        except Exception:
            log.exception("secretary: _handle_query failed")
            return "query_error"

    # ── Librarian consultation ────────────────────────────────────────────────

    def _consult_librarian(self, query: str, tenant_id: str) -> str:
        """
        Query the Librarian API for document-enriched context.
        Returns the response text, or empty string on failure.
        The Librarian is the only allowed access path to KOS documents.
        """
        try:
            import httpx  # type: ignore[import]

            resp = httpx.post(
                f"{LIBRARIAN_API_URL}/internal/librarian/query",
                json={
                    "query": query,
                    "tenant_id": tenant_id,
                    "user_id": "secretary-agent",
                    "max_citations": 3,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
        except Exception as exc:
            log.warning("secretary: Librarian consultation failed: %s", exc)
            return ""

    # ── Scheduled report dispatch ─────────────────────────────────────────────

    def send_scheduled_report(
        self,
        tenant_id: str,
        report_type: str,
        recipients: list[str],
    ) -> dict:
        """
        Generate and send a scheduled report (daily/weekly/monthly).

        Called by Celery Beat via agents.secretary.scheduler tasks.
        """
        from agents.secretary.report_generator import ReportGenerator  # noqa: PLC0415
        from services.mail.sender import send_mail  # noqa: PLC0415

        db_conn = _get_db()
        try:
            generator = ReportGenerator()

            subject_map = {
                "daily_summary": "📊 Resumen Diario — KOS",
                "weekly_metrics": "📈 Métricas Semanales — KOS",
                "monthly_analysis": "📋 Análisis Mensual — KOS",
            }
            subject = subject_map.get(report_type, f"Reporte {report_type} — KOS")

            if report_type == "daily_summary":
                body_html, body_text = generator.generate_summary_report(tenant_id)
            elif report_type == "weekly_metrics":
                body_html, body_text = generator.generate_weekly_report(tenant_id)
            else:
                body_html, body_text = generator.generate_monthly_report(tenant_id)

            result = send_mail(
                from_address=MAIL_SECRETARIO_ADDRESS,
                to_addresses=recipients,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                tenant_id=tenant_id,
                trigger_type="scheduled_report",
                trigger_detail={"report_type": report_type},
                db_conn=db_conn,
            )

            # Update last_sent_at in mail_report_schedules
            if result["success"]:
                with db_conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE mail_report_schedules
                        SET last_sent_at = NOW()
                        WHERE tenant_id = %s AND report_type = %s
                        """,
                        (tenant_id, report_type),
                    )
                db_conn.commit()

            return result
        except Exception:
            db_conn.rollback()
            log.exception(
                "secretary: send_scheduled_report failed (type=%s, tenant=%s)",
                report_type,
                tenant_id,
            )
            return {"success": False, "error": "internal_error"}
        finally:
            db_conn.close()

    # ── Anomaly alerting ──────────────────────────────────────────────────────

    def detect_and_alert(self, tenant_id: str, metric_data: dict) -> dict:
        """
        Check metric_data against active alert rules and send alerts as needed.

        Respects min_interval_hours to prevent alert fatigue.
        """
        from agents.secretary.alert_detector import AlertDetector  # noqa: PLC0415
        from services.mail.sender import send_mail  # noqa: PLC0415
        from agents.secretary.report_generator import ReportGenerator  # noqa: PLC0415

        db_conn = _get_db()
        try:
            detector = AlertDetector()
            triggered = detector.check_rules(tenant_id, metric_data, db_conn)
            alerts_sent = 0

            for alert in triggered:
                generator = ReportGenerator()
                body_html, body_text = generator.generate_alert_email(
                    tenant_id, alert
                )
                result = send_mail(
                    from_address=MAIL_SECRETARIO_ADDRESS,
                    to_addresses=alert["recipients"],
                    subject=f"🚨 Alerta: {alert['rule_name']}",
                    body_html=body_html,
                    body_text=body_text,
                    tenant_id=tenant_id,
                    trigger_type="anomaly_alert",
                    trigger_detail=alert,
                    db_conn=db_conn,
                )
                if result["success"]:
                    alerts_sent += 1
                    # Update last_triggered_at
                    with db_conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE mail_alert_rules
                            SET last_triggered_at = NOW()
                            WHERE id = %s
                            """,
                            (alert["rule_id"],),
                        )
                    db_conn.commit()

            return {"alerts_sent": alerts_sent, "rules_checked": len(triggered)}
        except Exception:
            db_conn.rollback()
            log.exception("secretary: detect_and_alert failed for tenant %s", tenant_id)
            return {"alerts_sent": 0, "error": "internal_error"}
        finally:
            db_conn.close()
