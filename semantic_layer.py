# semantic_layer.py
import logging
from typing import Dict, List, Optional
import asyncio
from litellm import acompletion
from backend.config import settings

logger = logging.getLogger(__name__)

class SemanticLayer:
    """
    Automatically generates human-readable descriptions for tables and columns
    using LLM analysis of sample data and naming patterns.
    Enriches schema with business context.
    """
    
    def __init__(self, db_connector):
        self.db = db_connector
        self.cache = {}  # Cache generated descriptions
    
    async def enrich_schema(self, schema: Dict) -> Dict:
        """
        Enrich schema with auto-generated descriptions for tables and columns.
        """
        enriched_schema = {"tables": []}
        
        for table in schema.get("tables", []):
            table_name = table.get("name")
            
            # Check cache first
            if table_name in self.cache:
                enriched_schema["tables"].append(self.cache[table_name])
                continue
            
            # Generate description for table
            table_desc = await self._generate_table_description(table)
            
            # Generate descriptions for columns
            enriched_columns = []
            for col in table.get("columns", []):
                col_name = col.get("name")
                col_desc = self._generate_column_description(
                    col_name, 
                    col.get("type"),
                    table.get("samples", [])
                )
                synonyms = self.get_column_synonyms(col_name)
                enriched_columns.append({
                    **col,
                    "description": col_desc,
                    "business_name": self._to_business_name(col_name),
                    "synonyms": synonyms
                })
            
            enriched_table = {
                **table,
                "description": table_desc,
                "columns": enriched_columns,
                "categorical_values": await self._fetch_categorical_values(table_name, table.get("columns", []))
            }
            
            self.cache[table_name] = enriched_table
            enriched_schema["tables"].append(enriched_table)
        
        return enriched_schema
    
    async def _fetch_categorical_values(self, table_name: str, columns: List[Dict]) -> List[str]:
        """Fetch distinct values for text columns that might be categorical."""
        categorical_vals = []
        for col in columns:
            col_type = col.get("type", "").lower()
            col_name = col.get("name", "").lower()
            if "char" in col_type or "text" in col_type or "string" in col_type:
                # Exclude columns that are likely unique IDs or timestamps
                if "id" in col_name and not col_name.endswith("_id"):
                    continue
                if col_name in ["created_at", "updated_at", "timestamp"]:
                    continue
                try:
                    # Get top 50 distinct values
                    query = f"SELECT DISTINCT {col_name} FROM {table_name} WHERE {col_name} IS NOT NULL LIMIT 50"
                    res = await self.db.execute_query(query)
                    for row in res.get("rows", []):
                        val = row.get(col.get("name"))
                        if val and isinstance(val, str) and len(val) > 2:
                            categorical_vals.append(val)
                except Exception as e:
                    logger.debug(f"Failed to fetch categorical values for {table_name}.{col_name}: {e}")
        return list(set(categorical_vals))

    async def _generate_table_description(self, table: Dict) -> str:
        """
        Generate a business-friendly table description programmatically.
        """
        table_name = table.get("name")
        columns = [c.get("name") for c in table.get("columns", [])]
        
        # 1. Check for manual user-provided descriptions first
        try:
            import json, os
            desc_file = os.path.join("config", "table_descriptions.json")
            if os.path.exists(desc_file):
                with open(desc_file, "r") as f:
                    manual_descs = json.load(f)
                    if table_name in manual_descs:
                        return manual_descs[table_name]
        except Exception as e:
            logger.warning(f"Failed to load manual descriptions: {e}")
        
        # 2. Quick heuristic descriptions for common patterns
        name_lower = table_name.lower()
        if "ega" in name_lower:
            return "Excess Give Away (EGA) details per machine and variant"
        elif "oee" in name_lower:
            return "Overall Equipment Effectiveness metrics per machine"
        elif "wastage" in name_lower or "waste" in name_lower:
            return "Production wastage and scrap records with reasons"
        elif "employee" in name_lower or "staff" in name_lower:
            return "Employee list with roles, certifications and shift assignments"
        elif "feeder" in name_lower and "stat" in name_lower:
            return "Feeder cycle statistics and amplitude performance data"
        elif "feedback" in name_lower or "production" in name_lower:
            return f"Production feedback and performance data tracking actual vs target metrics"
        elif "silo" in name_lower or "inventory" in name_lower:
            return f"Inventory levels and stock tracking for raw materials"
        elif "meter" in name_lower or "power" in name_lower or "electric" in name_lower:
            return f"Energy consumption and power usage monitoring"
        elif "humidity" in name_lower or "temperature" in name_lower:
            return f"Environmental conditions monitoring (temperature, humidity, etc.)"
        elif "error" in name_lower or "log" in name_lower or "event" in name_lower:
            return f"System events, errors, and operational logs"
        elif "setting" in name_lower or "config" in name_lower:
            return f"Machine parameters, limits, and golden threshold settings"
        elif "assign" in name_lower or "schedule" in name_lower:
            return f"Staff scheduling, shifts, and team assignments"
        elif "cert" in name_lower or "train" in name_lower:
            return f"Operator certifications, skills, and training levels"
        elif "order" in name_lower or "client" in name_lower or "sale" in name_lower:
            return f"Sales orders, client specifications, and shipment records"
            
        return f"Data table containing {', '.join(columns[:3])} and related industrial information"
    
    def _generate_column_description(self, col_name: str, col_type: str, samples: List[Dict]) -> str:
        """
        Generate human-readable column description based on name and sample data.
        """
        name_lower = col_name.lower()
        
        # Common patterns
        if name_lower in ["id", "uuid", "guid"]:
            return "Unique identifier"
        elif "created" in name_lower or "timestamp" in name_lower or "date" in name_lower:
            return "Timestamp of record creation"
        elif "updated" in name_lower or "modified" in name_lower:
            return "Last modification timestamp"
        elif "actual" in name_lower and "weight" in name_lower:
            return "Actual measured weight of produced item"
        elif "target" in name_lower and "weight" in name_lower:
            return "Target/expected weight specification"
        elif "actual" in name_lower and "speed" in name_lower:
            return "Actual production line speed"
        elif "target" in name_lower and "speed" in name_lower:
            return "Target/optimal production speed"
        elif "variant" in name_lower or "product" in name_lower:
            return "Product variant or SKU identifier"
        elif "shift" in name_lower:
            return "Work shift identifier (morning/afternoon/night)"
        elif "machine" in name_lower or "line" in name_lower:
            return "Production line or machine identifier"
        elif "cost" in name_lower:
            return "Monetary cost value"
        elif "level" in name_lower:
            return "Quantity or level measurement"
        elif "percent" in name_lower or "pct" in name_lower:
            return "Percentage value"
        elif "count" in name_lower or "total" in name_lower:
            return "Count or total quantity"
        elif "error" in name_lower or "status" in name_lower:
            return "Status or error code"
        
        # Analyze sample data
        if samples and col_name in samples[0]:
            sample_val = samples[0][col_name]
            if isinstance(sample_val, (int, float)):
                return f"Numeric measurement ({col_type})"
            elif isinstance(sample_val, str):
                return f"Text/categorical field ({col_type})"
        
        return f"Data field of type {col_type}"
    
    def _to_business_name(self, col_name: str) -> str:
        """
        Convert technical column name to business-friendly name.
        Example: actual_weight -> Actual Weight
        """
        # Replace underscores with spaces and title case
        business_name = col_name.replace("_", " ").title()
        
        # Handle common abbreviations
        replacements = {
            "Id": "ID",
            "Uuid": "UUID",
            "Ega": "EGA",
            "Oee": "OEE",
            "Kg": "KG",
            "Pct": "Percent",
            "Qty": "Quantity",
            "Avg": "Average",
            "Min": "Minimum",
            "Max": "Maximum",
            "Std": "Standard",
            "Temp": "Temperature"
        }
        
        for old, new in replacements.items():
            business_name = business_name.replace(old, new)
        
        return business_name
    
    def get_column_synonyms(self, col_name: str) -> List[str]:
        """
        Return common synonyms for a column name to improve query understanding.
        """
        synonyms_map = {
            "actual_weight": ["real weight", "measured weight", "final weight", "produced weight"],
            "target_weight": ["expected weight", "goal weight", "spec weight"],
            "actual_speed": ["real speed", "current speed", "production rate"],
            "variant": ["product", "sku", "item", "product type"],
            "shift": ["work shift", "shift time", "shift period"],
            "created_at": ["timestamp", "date", "time", "created date"],
            "cost": ["price", "expense", "charge"],
            "level_kg": ["inventory", "stock", "quantity"],
            "ega_percent": ["excess giveaway", "give away percent", "extra weight", "overweight percent"],
            "oee_percent": ["overall efficiency", "equipment effectiveness", "oee score"],
            "unix_timestamp": ["timestamp", "time", "date", "recorded at", "log time"],
            "machine_id": ["machine", "loop", "weigher", "line id", "machine name"],
            "grammage": ["weight", "pack size", "gram", "grams", "g", "package weight"],
            "topic": ["feeder id", "feeder name", "machine topic"]
        }
        
        return synonyms_map.get(col_name.lower(), [])

    def invalidate_cache(self, table_name: str = None):
        if table_name:
            self.cache.pop(table_name, None)
        else:
            self.cache.clear()
        logger.info(f"Semantic cache invalidated: {table_name or 'all'}")
