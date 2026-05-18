# analytics_engine.py
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)

class AnalyticsEngine:
    """
    Advanced analytics engine for automatic anomaly detection, trend analysis,
    and hidden pattern discovery in time-series industrial data.
    """
    
    def __init__(self, db_connector):
        self.db = db_connector
    
    async def detect_anomalies(self, table: str, metric_column: str, 
                               time_column: str = "created_at",
                               threshold_std: float = 2.5) -> Dict:
        """
        Detect statistical anomalies using Z-score method.
        Returns outlier records that deviate significantly from the mean.
        """
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
                           time_column: str = "created_at",
                           window_days: int = 7) -> Dict:
        """
        Detect trends using linear regression on time-series data.
        Returns trend direction, slope, and forecast.
        """
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
                                   time_column: str = "created_at") -> Dict:
        """
        Detect hourly/daily patterns (e.g., performance drops at specific hours).
        """
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
            
            # Find peak and low hours
            if values:
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
    
    async def auto_insights(self, query: str, table: str, metric_column: str) -> str:
        """
        Automatically run multiple analyses and generate insights summary.
        """
        insights = []
        
        # Run analyses in parallel
        anomaly_task = self.detect_anomalies(table, metric_column)
        trend_task = self.detect_trends(table, metric_column)
        time_pattern_task = self.analyze_time_patterns(table, metric_column)
        
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
