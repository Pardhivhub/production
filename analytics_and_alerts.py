"""
Analytics & Alerts Layer - Performs anomaly detection, trend analysis, and continuous alert monitoring on manufacturing data
"""
import asyncio
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

TIME_COLUMN_MAP = {
    "oee_details_data": "start_time",
    "ega_details_data": "start_time",
    "production_speed_details_data": "start_time",
    "wastage_records": "production_start_time",
    "gsm_usage_details": "date",
}

METRIC_COLUMN_MAP = {
    "oee_details_data": "downtime_mins",
    "ega_details_data": "ega_percent",
    "production_speed_details_data": "target_speed",
    "wastage_records": "wastage_kg",
    "gsm_usage_details": "gsm",
}

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


class AnalyticsEngine:
    """
    Advanced analytics engine for automatic anomaly detection, trend analysis,
    and hidden pattern discovery in time-series industrial data.
    """
    
    def __init__(self, db_connector):
        self.db = db_connector
    
    async def detect_anomalies(self, table: str, metric_column: str,
                               time_column: str = None,
                               threshold_std: float = 2.5) -> Dict:
        """
        Detect statistical anomalies using Z-score method.
        Returns outlier records that deviate significantly from the mean.
        """
        time_column = time_column or TIME_COLUMN_MAP.get(table, "start_time")
        try:
            # Fetch recent data
            sql = f"""
            SELECT {time_column}, {metric_column}
            FROM {table}
            WHERE {metric_column} IS NOT NULL
            ORDER BY {time_column} DESC
            LIMIT 1000
            """
            result = await self.db.execute_query(sql)
            
            if not result.get("rows") or len(result["rows"]) < 10:
                return {"anomalies": [], "message": "Insufficient data for anomaly detection"}
            
            values = [row[metric_column] for row in result["rows"]]
            mean = np.mean(values)
            std = np.std(values)
            
            anomalies = []
            for row in result["rows"]:
                z_score = abs((row[metric_column] - mean) / std) if std > 0 else 0
                if z_score > threshold_std:
                    anomalies.append({
                        "timestamp": str(row[time_column]),
                        "value": row[metric_column],
                        "z_score": round(z_score, 2),
                        "deviation_percent": round(((row[metric_column] - mean) / mean) * 100, 2)
                    })
            
            return {
                "anomalies": anomalies[:20],  # Top 20 anomalies
                "stats": {
                    "mean": round(mean, 2),
                    "std": round(std, 2),
                    "total_records": len(values),
                    "anomaly_count": len(anomalies)
                }
            }
        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            return {"anomalies": [], "error": str(e)}
    
    async def detect_trends(self, table: str, metric_column: str,
                           time_column: str = None,
                           window_days: int = 7) -> Dict:
        """
        Detect trends using linear regression on time-series data.
        Returns trend direction, slope, and forecast.
        """
        time_column = time_column or TIME_COLUMN_MAP.get(table, "start_time")
        try:
            sql = f"""
            SELECT {time_column}, {metric_column}
            FROM {table}
            WHERE {metric_column} IS NOT NULL
            AND {time_column} >= NOW() - INTERVAL '{window_days} days'
            ORDER BY {time_column} ASC
            """
            result = await self.db.execute_query(sql)
            
            if not result.get("rows") or len(result["rows"]) < 5:
                return {"trend": "insufficient_data"}
            
            # Simple linear regression
            x = np.arange(len(result["rows"]))
            y = np.array([row[metric_column] for row in result["rows"]])
            
            # Calculate slope using least squares
            x_mean = np.mean(x)
            y_mean = np.mean(y)
            slope = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)
            intercept = y_mean - slope * x_mean
            
            # Forecast next value
            next_x = len(x)
            forecast = slope * next_x + intercept
            
            # Determine trend direction
            if abs(slope) < 0.01:
                direction = "stable"
            elif slope > 0:
                direction = "increasing"
            else:
                direction = "decreasing"
            
            return {
                "trend": direction,
                "slope": round(slope, 4),
                "forecast_next": round(forecast, 2),
                "current_value": round(y[-1], 2),
                "change_percent": round((slope / y_mean) * 100, 2) if y_mean != 0 else 0,
                "data_points": len(result["rows"])
            }
        except Exception as e:
            logger.error(f"Trend detection failed: {e}")
            return {"trend": "error", "error": str(e)}
    
    async def find_correlations(self, table: str, columns: List[str],
                                min_correlation: float = 0.7) -> List[Dict]:
        """
        Find strong correlations between numeric columns.
        Useful for discovering hidden relationships.
        """
        try:
            if len(columns) < 2:
                return []
            
            # Fetch data for all columns
            col_str = ", ".join(columns)
            sql = f"SELECT {col_str} FROM {table} WHERE {' AND '.join([f'{c} IS NOT NULL' for c in columns])} LIMIT 1000"
            result = await self.db.execute_query(sql)
            
            if not result.get("rows") or len(result["rows"]) < 10:
                return []
            
            # Build correlation matrix
            correlations = []
            for i, col1 in enumerate(columns):
                for col2 in columns[i+1:]:
                    values1 = np.array([row[col1] for row in result["rows"]])
                    values2 = np.array([row[col2] for row in result["rows"]])
                    
                    # Calculate Pearson correlation
                    corr = np.corrcoef(values1, values2)[0, 1]
                    
                    if abs(corr) >= min_correlation:
                        correlations.append({
                            "column1": col1,
                            "column2": col2,
                            "correlation": round(corr, 3),
                            "strength": "strong" if abs(corr) > 0.8 else "moderate"
                        })
            
            return sorted(correlations, key=lambda x: abs(x["correlation"]), reverse=True)
        except Exception as e:
            logger.error(f"Correlation analysis failed: {e}")
            return []
    
    async def detect_shift_patterns(self, table: str, metric_column: str,
                                   shift_column: str = "shift") -> Dict:
        """
        Compare performance across shifts to identify best/worst performing shifts.
        """
        try:
            sql = f"""
            SELECT {shift_column}, 
                   AVG({metric_column}) as avg_value,
                   MIN({metric_column}) as min_value,
                   MAX({metric_column}) as max_value,
                   COUNT(*) as record_count
            FROM {table}
            WHERE {metric_column} IS NOT NULL
            GROUP BY {shift_column}
            ORDER BY avg_value DESC
            """
            result = await self.db.execute_query(sql)
            
            if not result.get("rows"):
                return {"shifts": []}
            
            shifts = []
            for row in result["rows"]:
                shifts.append({
                    "shift": row[shift_column],
                    "average": round(row["avg_value"], 2),
                    "min": round(row["min_value"], 2),
                    "max": round(row["max_value"], 2),
                    "records": row["record_count"]
                })
            
            # Find best and worst
            best_shift = shifts[0] if shifts else None
            worst_shift = shifts[-1] if shifts else None
            
            return {
                "shifts": shifts,
                "best_shift": best_shift,
                "worst_shift": worst_shift,
                "performance_gap": round(best_shift["average"] - worst_shift["average"], 2) if best_shift and worst_shift else 0
            }
        except Exception as e:
            logger.error(f"Shift pattern analysis failed: {e}")
            return {"shifts": [], "error": str(e)}
    
    async def detect_recurring_failures(self, table: str, 
                                       error_column: str = "error_code",
                                       time_column: str = "created_at",
                                       min_occurrences: int = 3) -> List[Dict]:
        """
        Identify recurring error patterns or failure modes.
        """
        try:
            sql = f"""
            SELECT {error_column}, 
                   COUNT(*) as occurrence_count,
                   MIN({time_column}) as first_seen,
                   MAX({time_column}) as last_seen
            FROM {table}
            WHERE {error_column} IS NOT NULL 
            AND {error_column} != ''
            GROUP BY {error_column}
            HAVING COUNT(*) >= {min_occurrences}
            ORDER BY occurrence_count DESC
            LIMIT 20
            """
            result = await self.db.execute_query(sql)
            
            if not result.get("rows"):
                return []
            
            failures = []
            for row in result["rows"]:
                failures.append({
                    "error": row[error_column],
                    "occurrences": row["occurrence_count"],
                    "first_seen": str(row["first_seen"]),
                    "last_seen": str(row["last_seen"])
                })
            
            return failures
        except Exception as e:
            logger.error(f"Recurring failure detection failed: {e}")
            return []
    
    async def analyze_time_patterns(self, table: str, metric_column: str,
                                   time_column: str = None) -> Dict:
        """
        Detect hourly/daily patterns (e.g., performance drops at specific hours).
        """
        time_column = time_column or TIME_COLUMN_MAP.get(table, "start_time")
        try:
            sql = f"""
            SELECT EXTRACT(HOUR FROM {time_column}) as hour,
                   AVG({metric_column}) as avg_value,
                   COUNT(*) as record_count
            FROM {table}
            WHERE {metric_column} IS NOT NULL
            GROUP BY EXTRACT(HOUR FROM {time_column})
            ORDER BY hour
            """
            result = await self.db.execute_query(sql)
            
            if not result.get("rows"):
                return {"hourly_patterns": []}
            
            patterns = []
            values = []
            for row in result["rows"]:
                patterns.append({
                    "hour": int(row["hour"]),
                    "average": round(row["avg_value"], 2),
                    "records": row["record_count"]
                })
                values.append(row["avg_value"])
            
            # Find peak and low hours (only makes sense if there is more than 1 distinct hour of data)
            if values and len(values) > 1:
                max_val = max(values)
                min_val = min(values)
                peak_hour = patterns[values.index(max_val)]["hour"]
                low_hour = patterns[values.index(min_val)]["hour"]
                
                return {
                    "hourly_patterns": patterns,
                    "peak_hour": peak_hour,
                    "low_hour": low_hour,
                    "peak_value": round(max_val, 2),
                    "low_value": round(min_val, 2),
                    "variance": round(max_val - min_val, 2)
                }
            
            return {"hourly_patterns": patterns}
        except Exception as e:
            logger.error(f"Time pattern analysis failed: {e}")
            return {"hourly_patterns": [], "error": str(e)}
    
    async def auto_insights(self, query: str, table: str, metric_column: str, time_column: str = None) -> str:
        """
        Automatically run multiple analyses and generate insights summary.
        """
        time_column = time_column or TIME_COLUMN_MAP.get(table, "start_time")
        # Only run on known production tables
        if table not in TIME_COLUMN_MAP:
            return ""
        insights = []
        
        # Run analyses in parallel
        anomaly_task = self.detect_anomalies(table, metric_column, time_column=time_column)
        trend_task = self.detect_trends(table, metric_column, time_column=time_column)
        time_pattern_task = self.analyze_time_patterns(table, metric_column, time_column=time_column)
        
        anomalies, trends, time_patterns = await asyncio.gather(
            anomaly_task, trend_task, time_pattern_task, return_exceptions=True
        )
        
        # Build insights text
        if isinstance(trends, dict) and trends.get("trend"):
            if trends["trend"] == "increasing":
                insights.append(f"📈 **Trend Alert**: {metric_column} is increasing by {trends.get('change_percent', 0)}% (slope: {trends.get('slope', 0)})")
            elif trends["trend"] == "decreasing":
                insights.append(f"📉 **Trend Alert**: {metric_column} is decreasing by {trends.get('change_percent', 0)}% (slope: {trends.get('slope', 0)})")
        
        if isinstance(anomalies, dict) and anomalies.get("anomalies"):
            count = len(anomalies["anomalies"])
            insights.append(f"⚠️ **Anomaly Detection**: Found {count} outliers in the last 1000 records (threshold: 2.5σ)")
        
        if isinstance(time_patterns, dict) and time_patterns.get("peak_hour") is not None:
            insights.append(f"⏰ **Time Pattern**: Peak performance at hour {time_patterns['peak_hour']}:00, lowest at {time_patterns['low_hour']}:00")
        
        if insights:
            return "\n\n**🔍 Automatic Insights:**\n" + "\n".join(insights)
        
        return ""


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
