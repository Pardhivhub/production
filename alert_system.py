# alert_system.py
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)

class AlertSystem:
    """
    Proactive monitoring and alerting system that continuously checks
    for critical conditions and anomalies in production data.
    """
    
    def __init__(self, db_connector):
        self.db = db_connector
        self.alert_rules = []
        self.alert_history = []
        self._setup_default_rules()
    
    def _setup_default_rules(self):
        """Initialize default alert rules for manufacturing scenarios."""
        self.alert_rules = [
            {
                "name": "High EGA Alert",
                "condition": "ega_percent > 5.0",
                "severity": "high",
                "message": "Excess Give Away exceeds 5% - significant material waste detected"
            },
            {
                "name": "Low Speed Alert",
                "condition": "actual_speed < target_speed * 0.8",
                "severity": "medium",
                "message": "Production speed is below 80% of target"
            },
            {
                "name": "Zero Production Alert",
                "condition": "actual_weight = 0",
                "severity": "critical",
                "message": "Zero production detected - possible line stoppage"
            },
            {
                "name": "High Power Cost Alert",
                "condition": "cost > 1000",
                "severity": "medium",
                "message": "Electricity cost exceeds $1000 threshold"
            },
            {
                "name": "Low Inventory Alert",
                "condition": "level_kg < 100",
                "severity": "high",
                "message": "Raw material inventory critically low"
            }
        ]
    
    async def check_alerts(self, table: str, time_window_minutes: int = 60) -> List[Dict]:
        """
        Check all alert rules against recent data.
        Returns list of triggered alerts.
        """
        triggered_alerts = []
        
        for rule in self.alert_rules:
            try:
                alert = await self._evaluate_rule(rule, table, time_window_minutes)
                if alert:
                    triggered_alerts.append(alert)
                    self.alert_history.append({
                        **alert,
                        "timestamp": datetime.now().isoformat()
                    })
            except Exception as e:
                logger.warning(f"Alert rule '{rule['name']}' evaluation failed: {e}")
        
        return triggered_alerts
    
    async def _evaluate_rule(self, rule: Dict, table: str, time_window: int) -> Optional[Dict]:
        """
        Evaluate a single alert rule against recent data.
        """
        condition = rule["condition"]
        
        # Parse condition to extract column and threshold
        # Simple parser for common patterns
        if "ega_percent" in condition:
            return await self._check_ega_alert(table, time_window, rule)
        elif "actual_speed" in condition and "target_speed" in condition:
            return await self._check_speed_alert(table, time_window, rule)
        elif "actual_weight = 0" in condition:
            return await self._check_zero_production_alert(table, time_window, rule)
        elif "cost" in condition:
            return await self._check_cost_alert(table, time_window, rule)
        elif "level_kg" in condition:
            return await self._check_inventory_alert(table, time_window, rule)
        
        return None
    
    async def _check_ega_alert(self, table: str, time_window: int, rule: Dict) -> Optional[Dict]:
        """Check for high EGA percentage."""
        try:
            sql = f"""
            SELECT ((SUM(actual_weight) - SUM(target_weight)) / NULLIF(SUM(actual_weight), 0)) * 100 AS ega_percent
            FROM {table}
            WHERE created_at >= NOW() - INTERVAL '{time_window} minutes'
            """
            result = await self.db.execute_query(sql)
            
            if result.get("rows") and result["rows"][0].get("ega_percent"):
                ega = result["rows"][0]["ega_percent"]
                if ega > 5.0:
                    return {
                        "rule_name": rule["name"],
                        "severity": rule["severity"],
                        "message": rule["message"],
                        "current_value": round(ega, 2),
                        "threshold": 5.0,
                        "table": table
                    }
        except Exception as e:
            logger.debug(f"EGA alert check skipped for {table}: {e}")
        
        return None
    
    async def _check_speed_alert(self, table: str, time_window: int, rule: Dict) -> Optional[Dict]:
        """Check for low production speed."""
        try:
            sql = f"""
            SELECT AVG(actual_speed) as avg_actual, AVG(target_speed) as avg_target
            FROM {table}
            WHERE created_at >= NOW() - INTERVAL '{time_window} minutes'
            AND actual_speed IS NOT NULL AND target_speed IS NOT NULL
            """
            result = await self.db.execute_query(sql)
            
            if result.get("rows"):
                row = result["rows"][0]
                if row.get("avg_actual") and row.get("avg_target"):
                    if row["avg_actual"] < row["avg_target"] * 0.8:
                        return {
                            "rule_name": rule["name"],
                            "severity": rule["severity"],
                            "message": rule["message"],
                            "current_value": round(row["avg_actual"], 2),
                            "threshold": round(row["avg_target"] * 0.8, 2),
                            "table": table
                        }
        except Exception as e:
            logger.debug(f"Speed alert check skipped for {table}: {e}")
        
        return None
    
    async def _check_zero_production_alert(self, table: str, time_window: int, rule: Dict) -> Optional[Dict]:
        """Check for zero production records."""
        try:
            sql = f"""
            SELECT COUNT(*) as zero_count
            FROM {table}
            WHERE created_at >= NOW() - INTERVAL '{time_window} minutes'
            AND actual_weight = 0
            """
            result = await self.db.execute_query(sql)
            
            if result.get("rows") and result["rows"][0].get("zero_count", 0) > 5:
                return {
                    "rule_name": rule["name"],
                    "severity": rule["severity"],
                    "message": rule["message"],
                    "current_value": result["rows"][0]["zero_count"],
                    "threshold": 5,
                    "table": table
                }
        except Exception as e:
            logger.debug(f"Zero production alert check skipped for {table}: {e}")
        
        return None
    
    async def _check_cost_alert(self, table: str, time_window: int, rule: Dict) -> Optional[Dict]:
        """Check for high electricity costs."""
        try:
            sql = f"""
            SELECT SUM(cost) as total_cost
            FROM {table}
            WHERE created_at >= NOW() - INTERVAL '{time_window} minutes'
            """
            result = await self.db.execute_query(sql)
            
            if result.get("rows") and result["rows"][0].get("total_cost"):
                cost = result["rows"][0]["total_cost"]
                if cost > 1000:
                    return {
                        "rule_name": rule["name"],
                        "severity": rule["severity"],
                        "message": rule["message"],
                        "current_value": round(cost, 2),
                        "threshold": 1000,
                        "table": table
                    }
        except Exception as e:
            logger.debug(f"Cost alert check skipped for {table}: {e}")
        
        return None
    
    async def _check_inventory_alert(self, table: str, time_window: int, rule: Dict) -> Optional[Dict]:
        """Check for low inventory levels."""
        try:
            sql = f"""
            SELECT MIN(level_kg) as min_level
            FROM {table}
            WHERE created_at >= NOW() - INTERVAL '{time_window} minutes'
            """
            result = await self.db.execute_query(sql)
            
            if result.get("rows") and result["rows"][0].get("min_level") is not None:
                level = result["rows"][0]["min_level"]
                if level < 100:
                    return {
                        "rule_name": rule["name"],
                        "severity": rule["severity"],
                        "message": rule["message"],
                        "current_value": round(level, 2),
                        "threshold": 100,
                        "table": table
                    }
        except Exception as e:
            logger.debug(f"Inventory alert check skipped for {table}: {e}")
        
        return None
    
    def add_custom_rule(self, name: str, condition: str, severity: str, message: str):
        """Allow users to add custom alert rules."""
        self.alert_rules.append({
            "name": name,
            "condition": condition,
            "severity": severity,
            "message": message
        })
        logger.info(f"Added custom alert rule: {name}")
    
    def get_alert_history(self, limit: int = 50) -> List[Dict]:
        """Retrieve recent alert history."""
        return self.alert_history[-limit:]
    
    async def run_continuous_monitoring(self, schema: Dict, interval_seconds: int = 300):
        """
        Background task that continuously monitors all tables.
        Run this in a separate async task.
        """
        logger.info(f"Starting continuous monitoring (interval: {interval_seconds}s)")
        
        while True:
            try:
                all_alerts = []
                for table in schema.get("tables", []):
                    table_name = table.get("name")
                    alerts = await self.check_alerts(table_name, time_window_minutes=60)
                    all_alerts.extend(alerts)
                
                if all_alerts:
                    logger.warning(f"🚨 {len(all_alerts)} alerts triggered:")
                    for alert in all_alerts:
                        logger.warning(f"  - [{alert['severity'].upper()}] {alert['message']} (value: {alert['current_value']})")
                
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(interval_seconds)
