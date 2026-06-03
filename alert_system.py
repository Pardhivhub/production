# alert_system.py
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

def get_alert_tables() -> set:
    try:
        import json
        from pathlib import Path
        rules_path = Path(__file__).parent / "prompts" / "table_rules.json"
        if rules_path.exists():
            with open(rules_path, "r") as f:
                data = json.load(f)
                return set(data.get("ALERT_PRODUCTION_TABLES", []))
    except Exception as e:
        logger.error(f"Failed to load table_rules.json: {e}")
    return {"ega_details_data", "oee_details_data", "wastage_records"}

ALERT_PRODUCTION_TABLES = get_alert_tables()


class AlertSystem:
    """
    Proactive monitoring system that checks for critical conditions
    in production data. Only queries known production tables with
    correct triniti_db column names.
    """

    def __init__(self, db_connector):
        self.db = db_connector
        self.alert_history = []

    async def check_alerts(self, table: str, time_window_minutes: int = 60) -> List[Dict]:
        """
        Check alerts for a given table. Silently skips non-production tables.
        """
        if table not in ALERT_PRODUCTION_TABLES:
            return []

        triggered = []
        try:
            if table == "ega_details_data":
                alert = await self._check_ega_alert(table, time_window_minutes)
                if alert:
                    triggered.append(alert)

            elif table == "oee_details_data":
                alerts = await self._check_oee_alerts(table, time_window_minutes)
                triggered.extend(alerts)

            elif table == "wastage_records":
                alert = await self._check_wastage_alert(table, time_window_minutes)
                if alert:
                    triggered.append(alert)

        except Exception as e:
            logger.debug(f"Alert check skipped for {table}: {e}")

        for alert in triggered:
            self.alert_history.append({**alert, "timestamp": datetime.now().isoformat()})

        return triggered

    async def _check_ega_alert(self, table: str, time_window: int) -> Optional[Dict]:
        """Check for high EGA using correct triniti_db columns: t_weight, theoretical_pack_weight."""
        try:
            sql = f"""
            SELECT ROUND(((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight), 0))::numeric * 100, 2) AS ega_percent
            FROM {table}
            WHERE start_time >= NOW() - INTERVAL '{time_window} minutes'
            """
            result = await self.db.execute_query(sql)
            if result.get("rows") and result["rows"][0].get("ega_percent") is not None:
                ega = float(result["rows"][0]["ega_percent"])
                if ega > 5.0:
                    return {
                        "rule_name": "High EGA Alert",
                        "severity": "high",
                        "message": f"Excess Give Away is {ega:.2f}% — exceeds 5% threshold",
                        "current_value": ega,
                        "threshold": 5.0,
                        "table": table,
                    }
        except Exception as e:
            logger.debug(f"EGA alert skipped: {e}")
        return None

    async def _check_oee_alerts(self, table: str, time_window: int) -> List[Dict]:
        """Check OEE alerts: high downtime, zero good bags."""
        alerts = []
        try:
            sql = f"""
            SELECT
                SUM(downtime_mins) AS total_downtime,
                SUM(good_bags) AS total_good,
                SUM(failed_bags) AS total_failed
            FROM {table}
            WHERE start_time >= NOW() - INTERVAL '{time_window} minutes'
            """
            result = await self.db.execute_query(sql)
            if result.get("rows"):
                row = result["rows"][0]
                downtime = float(row.get("total_downtime") or 0)
                good = int(row.get("total_good") or 0)
                failed = int(row.get("total_failed") or 0)

                if downtime > 120:
                    alerts.append({
                        "rule_name": "High Downtime Alert",
                        "severity": "high",
                        "message": f"Total downtime in last {time_window} mins is {downtime:.1f} mins",
                        "current_value": downtime,
                        "threshold": 120,
                        "table": table,
                    })
                if good == 0 and failed > 0:
                    alerts.append({
                        "rule_name": "Zero Good Bags Alert",
                        "severity": "critical",
                        "message": "Zero good bags produced — possible line stoppage",
                        "current_value": 0,
                        "threshold": 1,
                        "table": table,
                    })
        except Exception as e:
            logger.debug(f"OEE alert skipped: {e}")
        return alerts

    async def _check_wastage_alert(self, table: str, time_window: int) -> Optional[Dict]:
        """Check for high manual wastage using production_start_time."""
        try:
            sql = f"""
            SELECT SUM(wastage_kg) AS total_wastage
            FROM {table}
            WHERE production_start_time >= NOW() - INTERVAL '{time_window} minutes'
            """
            result = await self.db.execute_query(sql)
            if result.get("rows") and result["rows"][0].get("total_wastage") is not None:
                wastage = float(result["rows"][0]["total_wastage"])
                if wastage > 50:
                    return {
                        "rule_name": "High Wastage Alert",
                        "severity": "medium",
                        "message": f"Total manual wastage is {wastage:.2f} kg — exceeds 50 kg threshold",
                        "current_value": wastage,
                        "threshold": 50,
                        "table": table,
                    }
        except Exception as e:
            logger.debug(f"Wastage alert skipped: {e}")
        return None

    def add_custom_rule(self, name: str, condition: str, severity: str, message: str):
        logger.info(f"Custom alert rule noted: {name}")

    def get_alert_history(self, limit: int = 50) -> List[Dict]:
        return self.alert_history[-limit:]

    async def run_continuous_monitoring(self, schema: dict, interval_seconds: int = 300):
        """
        Background coroutine — only checks production tables, never metadata/config tables.
        """
        logger.info(f"Starting continuous monitoring (interval: {interval_seconds}s)")
        while True:
            try:
                all_alerts = []
                for table_name in ALERT_PRODUCTION_TABLES:
                    alerts = await self.check_alerts(table_name, time_window_minutes=60)
                    all_alerts.extend(alerts)
                if all_alerts:
                    logger.warning(f"🚨 {len(all_alerts)} alerts triggered:")
                    for alert in all_alerts:
                        logger.warning(
                            f"  - [{alert['severity'].upper()}] {alert['message']} "
                            f"(value: {alert['current_value']})"
                        )
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(interval_seconds)
