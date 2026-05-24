"""
agents/secretary/alert_detector.py — Anomaly detection for the Secretary agent.

Checks incoming metric data against tenant-configured alert rules.
Respects min_interval_hours to prevent alert fatigue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2.extensions

log = logging.getLogger(__name__)


class AlertDetector:
    """
    Stateless anomaly detector.
    All persistence goes through the db_conn passed to check_rules().
    """

    def check_rules(
        self,
        tenant_id: str,
        metric_data: dict,
        db_conn: psycopg2.extensions.connection,
    ) -> list[dict]:
        """
        Evaluate all active alert rules for a tenant against the given metrics.

        Args:
            tenant_id:   Tenant UUID.
            metric_data: Dict of {metric_key: current_value}.
                         Example: {'ventas_diarias': 18500, 'documentos_procesados': 42}
            db_conn:     Open psycopg2 connection.

        Returns:
            List of triggered alert dicts, each with:
            {rule_id, rule_name, metric_key, threshold_pct, current_value,
             previous_value, change_pct, recipients}
        """
        triggered: list[dict] = []

        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, rule_name, metric_key, threshold_pct,
                           comparison_period, recipients, min_interval_hours,
                           last_triggered_at
                    FROM mail_alert_rules
                    WHERE tenant_id = %s AND is_active = TRUE
                    """,
                    (tenant_id,),
                )
                rules = cur.fetchall()
        except Exception:
            log.exception("alert_detector: failed to load rules for tenant %s", tenant_id)
            return []

        now = datetime.now(timezone.utc)

        for rule in rules:
            (
                rule_id, rule_name, metric_key, threshold_pct,
                comparison_period, recipients, min_interval_hours, last_triggered_at,
            ) = rule

            # Skip if metric not in current data
            current_value = metric_data.get(metric_key)
            if current_value is None:
                continue

            # Respect minimum alert interval
            if last_triggered_at:
                elapsed_hours = (now - last_triggered_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
                if elapsed_hours < min_interval_hours:
                    log.debug(
                        "alert_detector: rule '%s' skipped — last triggered %.1fh ago (min=%dh)",
                        rule_name,
                        elapsed_hours,
                        min_interval_hours,
                    )
                    continue

            # Get comparison (previous period) value
            previous_value = self._get_comparison_value(
                tenant_id, metric_key, comparison_period, db_conn
            )
            if previous_value is None or previous_value == 0:
                continue

            change_pct = ((current_value - previous_value) / previous_value) * 100

            # Check if threshold is breached
            # threshold_pct is signed: negative = drop, positive = spike
            if threshold_pct < 0:
                # Looking for drops
                triggered_now = change_pct <= threshold_pct
            else:
                # Looking for spikes
                triggered_now = change_pct >= threshold_pct

            if triggered_now:
                log.warning(
                    "alert_detector: rule '%s' triggered — %s changed %.1f%% (threshold: %.1f%%)",
                    rule_name,
                    metric_key,
                    change_pct,
                    threshold_pct,
                )
                triggered.append(
                    {
                        "rule_id": str(rule_id),
                        "rule_name": rule_name,
                        "metric_key": metric_key,
                        "threshold_pct": threshold_pct,
                        "current_value": current_value,
                        "previous_value": previous_value,
                        "change_pct": round(change_pct, 2),
                        "recipients": recipients or [],
                        "comparison_period": comparison_period,
                    }
                )

        return triggered

    def _get_comparison_value(
        self,
        tenant_id: str,
        metric_key: str,
        period: str,
        db_conn: psycopg2.extensions.connection,
    ) -> Optional[float]:
        """
        Retrieve the comparison period's value for a metric.

        Priority:
        1. KOS mail_messages / mail_outbound stats for built-in metrics.
        2. Returns None for unknown metrics (external MCP sources not wired here).

        Built-in metrics:
          mail_inbound_24h   — inbound mail count (previous 24h before last 24h)
          mail_outbound_24h  — sent mail count (same window)
          attachments_24h    — attachment count (same window)

        Period strings:
          'previous_day'  — compare to the 24h window before the last 24h
          'previous_week' — compare to 7–14 days ago
        """
        if period not in ("previous_day", "previous_week"):
            log.debug(
                "alert_detector: unknown comparison period '%s' for metric '%s'",
                period,
                metric_key,
            )
            return None

        interval_start, interval_end = (
            ("48 hours", "24 hours")
            if period == "previous_day"
            else ("14 days", "7 days")
        )

        # Built-in DB metrics
        try:
            with db_conn.cursor() as cur:
                if metric_key == "mail_inbound_24h":
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM mail_messages
                        WHERE tenant_id = %s
                          AND direction = 'inbound'
                          AND received_at BETWEEN
                              NOW() - make_interval(hours => %s)
                              AND NOW() - make_interval(hours => %s)
                        """,
                        (
                            tenant_id,
                            int(interval_start.split()[0]),
                            int(interval_end.split()[0]),
                        ),
                    )
                    return float(cur.fetchone()[0])

                if metric_key == "mail_outbound_24h":
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM mail_outbound
                        WHERE tenant_id = %s
                          AND status = 'sent'
                          AND sent_at BETWEEN
                              NOW() - make_interval(hours => %s)
                              AND NOW() - make_interval(hours => %s)
                        """,
                        (
                            tenant_id,
                            int(interval_start.split()[0]),
                            int(interval_end.split()[0]),
                        ),
                    )
                    return float(cur.fetchone()[0])

                if metric_key == "attachments_24h":
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM mail_attachments ma
                        JOIN mail_messages mm ON ma.message_id = mm.id
                        WHERE mm.tenant_id = %s
                          AND ma.created_at BETWEEN
                              NOW() - make_interval(hours => %s)
                              AND NOW() - make_interval(hours => %s)
                        """,
                        (
                            tenant_id,
                            int(interval_start.split()[0]),
                            int(interval_end.split()[0]),
                        ),
                    )
                    return float(cur.fetchone()[0])

        except Exception as exc:
            log.warning(
                "alert_detector: DB query for metric '%s' failed: %s",
                metric_key,
                exc,
            )
            return None

        # Unknown metric — log and return None
        # External MCP data sources are queried by the configured MCP tools,
        # not hard-coded here.
        log.debug(
            "alert_detector: no built-in comparison value for metric '%s' (period=%s)",
            metric_key,
            period,
        )
        return None
