# query_suggester.py
import logging
from typing import List, Dict
import re

logger = logging.getLogger(__name__)

class QuerySuggester:
    """
    Intelligent query suggestion engine that recommends follow-up questions
    based on current query results and schema context.
    """
    
    def __init__(self, schema: Dict):
        self.schema = schema
    
    def suggest_followups(self, user_query: str, sql: str, results: Dict, 
                         selected_tables: List[str]) -> List[str]:
        """
        Generate contextual follow-up question suggestions.
        """
        suggestions = []
        q_lower = user_query.lower()
        
        # 1. If query returned aggregates, suggest breakdowns
        if results.get("row_count") == 1 and results.get("rows"):
            row = results["rows"][0]
            # Check if it's an aggregate (has functions like avg, sum, count)
            if any(key in str(row.keys()).lower() for key in ["avg", "sum", "count", "total", "max", "min"]):
                suggestions.extend(self._suggest_breakdowns(selected_tables, user_query))
        
        # 2. If query has time filter, suggest different time ranges
        if any(word in q_lower for word in ["today", "yesterday", "last week", "last month"]):
            suggestions.append("Show me the same data for last month")
            suggestions.append("Compare this week vs last week")
        
        # 3. If query mentions a specific entity, suggest comparisons
        if any(word in q_lower for word in ["machine", "line", "variant", "shift"]):
            suggestions.append("Compare all machines/variants side by side")
            suggestions.append("Which one has the highest/lowest value?")
        
        # 4. If results show numeric data, suggest trend analysis
        if results.get("rows") and len(results["rows"]) > 1:
            numeric_cols = [k for k, v in results["rows"][0].items() if isinstance(v, (int, float))]
            if numeric_cols:
                suggestions.append(f"Show me the trend of {numeric_cols[0]} over time")
                suggestions.append(f"Find anomalies in {numeric_cols[0]}")
        
        # 5. Suggest root cause analysis
        if any(word in q_lower for word in ["low", "high", "problem", "issue", "error"]):
            suggestions.append("What factors correlate with this issue?")
            suggestions.append("When did this pattern start?")
        
        # 6. Suggest related metrics from KPI catalog
        suggestions.extend(self._suggest_related_metrics(user_query))
        
        # 7. If no results, suggest broader queries
        if results.get("row_count") == 0:
            suggestions.append("Show me all available data for this table")
            suggestions.append("What is the date range of available data?")
        
        # Deduplicate and limit
        unique_suggestions = list(dict.fromkeys(suggestions))
        return unique_suggestions[:5]
    
    def _suggest_breakdowns(self, tables: List[str], query: str) -> List[str]:
        """Suggest dimensional breakdowns based on available columns."""
        suggestions = []
        
        for table_name in tables:
            table = next((t for t in self.schema.get("tables", []) if t["name"] == table_name), None)
            if not table:
                continue
            
            # Find categorical columns
            categorical_cols = []
            for col in table.get("columns", []):
                col_name = col.get("name", "").lower()
                col_type = col.get("type", "").lower()
                
                # Identify likely categorical columns
                if any(cat in col_name for cat in ["variant", "shift", "machine", "line", "zone", "type", "category", "status"]):
                    categorical_cols.append(col.get("name"))
                elif "varchar" in col_type or "text" in col_type or "char" in col_type:
                    categorical_cols.append(col.get("name"))
            
            # Suggest breakdowns
            for col in categorical_cols[:3]:  # Top 3
                if col.lower() not in query.lower():
                    suggestions.append(f"Break down by {col}")
        
        return suggestions
    
    def _suggest_related_metrics(self, query: str) -> List[str]:
        """Suggest related KPIs based on query context."""
        suggestions = []
        q_lower = query.lower()
        
        # Manufacturing-specific suggestions
        if any(word in q_lower for word in ["ega", "excess", "give away", "weight"]):
            suggestions.append("What is the average speed for the same period?")
            suggestions.append("Show me total production volume")
        
        if any(word in q_lower for word in ["speed", "rate", "throughput"]):
            suggestions.append("Calculate EGA percent for this data")
            suggestions.append("Show me target vs actual comparison")
        
        if any(word in q_lower for word in ["efficiency", "oee", "performance"]):
            suggestions.append("What is the downtime breakdown?")
            suggestions.append("Show me quality metrics")
        
        if any(word in q_lower for word in ["power", "energy", "electricity"]):
            suggestions.append("What is the cost breakdown by meter?")
            suggestions.append("Show me peak demand hours")
        
        return suggestions
    
    def suggest_exploratory_queries(self, table_name: str) -> List[str]:
        """
        Generate exploratory queries for a new table the user hasn't queried yet.
        """
        table = next((t for t in self.schema.get("tables", []) if t["name"] == table_name), None)
        if not table:
            return []
        
        suggestions = [
            f"Show me a summary of {table_name}",
            f"What is the date range of data in {table_name}?",
            f"How many records are in {table_name}?",
        ]
        
        # Add column-specific suggestions
        columns = table.get("columns", [])
        numeric_cols = [c["name"] for c in columns if any(t in c.get("type", "").lower() for t in ["int", "float", "numeric", "decimal", "real"])]
        
        if numeric_cols:
            suggestions.append(f"What is the average {numeric_cols[0]}?")
            suggestions.append(f"Show me the distribution of {numeric_cols[0]}")
        
        return suggestions[:5]
