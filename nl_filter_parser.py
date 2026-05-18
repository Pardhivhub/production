# nl_filter_parser.py
import logging
import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import dateparser

logger = logging.getLogger(__name__)

class NLFilterParser:
    """
    Parses natural language time expressions and filters into SQL WHERE clauses.
    Handles complex temporal queries like "last 3 days", "between Jan and March", etc.
    """
    
    def __init__(self):
        self.time_patterns = {
            r"last (\d+) (hour|hours|day|days|week|weeks|month|months|year|years)": self._parse_last_n_period,
            r"past (\d+) (hour|hours|day|days|week|weeks|month|months)": self._parse_last_n_period,
            r"today": self._parse_today,
            r"yesterday": self._parse_yesterday,
            r"this (week|month|year)": self._parse_this_period,
            r"last (week|month|year)": self._parse_last_period,
            r"between (.+) and (.+)": self._parse_between,
            r"since (.+)": self._parse_since,
            r"before (.+)": self._parse_before,
            r"after (.+)": self._parse_after,
            r"in (january|february|march|april|may|june|july|august|september|october|november|december)": self._parse_month,
            r"in (\d{4})": self._parse_year,
        }
    
    def parse_temporal_filter(self, query: str, time_column: str = "created_at") -> Optional[str]:
        """
        Extract temporal filters from natural language query.
        Returns SQL WHERE clause fragment.
        """
        q_lower = query.lower()
        
        for pattern, handler in self.time_patterns.items():
            match = re.search(pattern, q_lower)
            if match:
                try:
                    return handler(match, time_column)
                except Exception as e:
                    logger.warning(f"Failed to parse temporal filter '{match.group()}': {e}")
        
        return None
    
    def _parse_last_n_period(self, match: re.Match, time_column: str) -> str:
        """Parse 'last N days/hours/weeks' patterns."""
        n = int(match.group(1))
        period = match.group(2).rstrip('s')  # Remove plural 's'
        
        return f"{time_column} >= NOW() - INTERVAL '{n} {period}'"
    
    def _parse_today(self, match: re.Match, time_column: str) -> str:
        """Parse 'today' pattern."""
        return f"DATE({time_column}) = CURRENT_DATE"
    
    def _parse_yesterday(self, match: re.Match, time_column: str) -> str:
        """Parse 'yesterday' pattern."""
        return f"DATE({time_column}) = CURRENT_DATE - INTERVAL '1 day'"
    
    def _parse_this_period(self, match: re.Match, time_column: str) -> str:
        """Parse 'this week/month/year' patterns."""
        period = match.group(1)
        
        if period == "week":
            return f"{time_column} >= DATE_TRUNC('week', CURRENT_DATE)"
        elif period == "month":
            return f"{time_column} >= DATE_TRUNC('month', CURRENT_DATE)"
        elif period == "year":
            return f"{time_column} >= DATE_TRUNC('year', CURRENT_DATE)"
        
        return None
    
    def _parse_last_period(self, match: re.Match, time_column: str) -> str:
        """Parse 'last week/month/year' patterns."""
        period = match.group(1)
        
        if period == "week":
            return f"{time_column} >= DATE_TRUNC('week', CURRENT_DATE) - INTERVAL '1 week' AND {time_column} < DATE_TRUNC('week', CURRENT_DATE)"
        elif period == "month":
            return f"{time_column} >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' AND {time_column} < DATE_TRUNC('month', CURRENT_DATE)"
        elif period == "year":
            return f"{time_column} >= DATE_TRUNC('year', CURRENT_DATE) - INTERVAL '1 year' AND {time_column} < DATE_TRUNC('year', CURRENT_DATE)"
        
        return None
    
    def _parse_between(self, match: re.Match, time_column: str) -> str:
        """Parse 'between X and Y' patterns."""
        start_str = match.group(1).strip()
        end_str = match.group(2).strip()
        
        # Use dateparser for flexible date parsing
        start_date = dateparser.parse(start_str)
        end_date = dateparser.parse(end_str)
        
        if start_date and end_date:
            return f"{time_column} BETWEEN '{start_date.date()}' AND '{end_date.date()}'"
        
        return None
    
    def _parse_since(self, match: re.Match, time_column: str) -> str:
        """Parse 'since X' patterns."""
        date_str = match.group(1).strip()
        date_obj = dateparser.parse(date_str)
        
        if date_obj:
            return f"{time_column} >= '{date_obj.date()}'"
        
        return None
    
    def _parse_before(self, match: re.Match, time_column: str) -> str:
        """Parse 'before X' patterns."""
        date_str = match.group(1).strip()
        date_obj = dateparser.parse(date_str)
        
        if date_obj:
            return f"{time_column} < '{date_obj.date()}'"
        
        return None
    
    def _parse_after(self, match: re.Match, time_column: str) -> str:
        """Parse 'after X' patterns."""
        date_str = match.group(1).strip()
        date_obj = dateparser.parse(date_str)
        
        if date_obj:
            return f"{time_column} > '{date_obj.date()}'"
        
        return None
    
    def _parse_month(self, match: re.Match, time_column: str) -> str:
        """Parse 'in January' patterns."""
        month_name = match.group(1).capitalize()
        month_num = datetime.strptime(month_name, "%B").month
        
        # Assume current year
        year = datetime.now().year
        return f"EXTRACT(MONTH FROM {time_column}) = {month_num} AND EXTRACT(YEAR FROM {time_column}) = {year}"
    
    def _parse_year(self, match: re.Match, time_column: str) -> str:
        """Parse 'in 2023' patterns."""
        year = match.group(1)
        return f"EXTRACT(YEAR FROM {time_column}) = {year}"
    
    def parse_comparison_filters(self, query: str, schema: Dict) -> List[str]:
        """
        Extract comparison filters like 'speed > 100', 'weight between 50 and 60'.
        Returns list of SQL WHERE clause fragments.
        """
        filters = []
        q_lower = query.lower()
        
        # Get all numeric columns from schema
        numeric_columns = []
        for table in schema.get("tables", []):
            for col in table.get("columns", []):
                if any(t in col.get("type", "").lower() for t in ["int", "float", "numeric", "decimal", "real"]):
                    numeric_columns.append(col.get("name"))
        
        # Pattern: column > value
        for col in numeric_columns:
            col_lower = col.lower()
            
            # Greater than
            match = re.search(rf"{col_lower}\s*>\s*(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} > {match.group(1)}")
            
            # Less than
            match = re.search(rf"{col_lower}\s*<\s*(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} < {match.group(1)}")
            
            # Equals
            match = re.search(rf"{col_lower}\s*=\s*(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} = {match.group(1)}")
            
            # Between
            match = re.search(rf"{col_lower}\s+between\s+(\d+\.?\d*)\s+and\s+(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} BETWEEN {match.group(1)} AND {match.group(2)}")
        
        return filters
    
    def parse_categorical_filters(self, query: str, schema: Dict) -> List[str]:
        """
        Extract categorical filters like 'variant = A', 'shift is morning'.
        Returns list of SQL WHERE clause fragments.
        """
        filters = []
        q_lower = query.lower()
        
        # Get all text columns from schema
        text_columns = []
        for table in schema.get("tables", []):
            for col in table.get("columns", []):
                if any(t in col.get("type", "").lower() for t in ["varchar", "text", "char"]):
                    text_columns.append(col.get("name"))
        
        # Pattern: column = 'value' or column is value
        for col in text_columns:
            col_lower = col.lower()
            
            # Equals pattern
            match = re.search(rf"{col_lower}\s*(?:=|is|equals)\s*['\"]?(\w+)['\"]?", q_lower)
            if match:
                value = match.group(1)
                filters.append(f"{col} = '{value}'")
            
            # IN pattern: "variant in (A, B, C)"
            match = re.search(rf"{col_lower}\s+in\s*\(([^)]+)\)", q_lower)
            if match:
                values = [v.strip().strip("'\"") for v in match.group(1).split(",")]
                values_str = ", ".join([f"'{v}'" for v in values])
                filters.append(f"{col} IN ({values_str})")
        
        return filters
    
    def build_where_clause(self, query: str, schema: Dict, time_column: str = "created_at") -> str:
        """
        Build complete WHERE clause from natural language query.
        Combines temporal, comparison, and categorical filters.
        """
        all_filters = []
        
        # Parse temporal filters
        temporal = self.parse_temporal_filter(query, time_column)
        if temporal:
            all_filters.append(temporal)
        
        # Parse comparison filters
        comparisons = self.parse_comparison_filters(query, schema)
        all_filters.extend(comparisons)
        
        # Parse categorical filters
        categorical = self.parse_categorical_filters(query, schema)
        all_filters.extend(categorical)
        
        if all_filters:
            return "WHERE " + " AND ".join(all_filters)
        
        return ""
