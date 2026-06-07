"""
Entity Mapper - Identifies which entity (machine, grammage, loop, variant) user is querying
"""
import re
from typing import Dict, List, Tuple

class EntityMapper:
    """Maps natural language queries to correct database entities"""
    
    ENTITY_KEYWORDS = {
        "machine": {
            "keywords": ["machine", "weigher", "equipment", "robot", "filler", "sealer"],
            "column": "machine_id",
            "group_by": ["machine_id", "machine_name"]
        },
        "grammage": {
            "keywords": ["grammage", "weight", "gram", "size", "sku"],
            "column": "grammage",
            "group_by": ["grammage"]
        },
        "variant": {
            "keywords": ["variant", "type", "ridge", "flat", "cut", "product"],
            "column": "variant",
            "group_by": ["variant"]
        },
        "loop": {
            "keywords": ["loop", "line"],
            "column": "loop_id",
            "group_by": ["loop_id"]
        },
        "shift": {
            "keywords": ["shift", "morning", "afternoon", "night", "overnight"],
            "column": "shift",
            "group_by": ["shift"]
        },
        "plant": {
            "keywords": ["plant", "factory", "site"],
            "column": "plant_id",
            "group_by": ["plant_id"]
        }
    }
    
    def detect_primary_entity(self, user_query: str) -> Tuple[str, str, List[str]]:
        """
        Detects what entity the user is asking about.
        
        Returns:
            (entity_name, column_name, group_by_columns)
            
        Example:
            "Which grammage had most bags" -> ("grammage", "grammage", ["grammage"])
            "Which machine had highest EGA" -> ("machine", "machine_id", ["machine_id", "machine_name"])
        """
        q_lower = user_query.lower()
        
        # Extract the "which X" or "what X" pattern
        which_pattern = re.search(r"which\s+(\w+)|what\s+(\w+)", q_lower)
        what_entity = None
        if which_pattern:
            what_entity = which_pattern.group(1) or which_pattern.group(2)
        
        # Score each entity based on keyword matches and position
        entity_scores = {}
        for entity, meta in self.ENTITY_KEYWORDS.items():
            score = 0
            
            # Boost score if entity appears in "which X" or "what X"
            if what_entity and any(kw in what_entity for kw in meta["keywords"]):
                score += 100
            
            # Add points for each keyword match
            for keyword in meta["keywords"]:
                if keyword in q_lower:
                    # Boost if keyword appears early in query
                    position = q_lower.find(keyword)
                    if position < 50:
                        score += 10
                    else:
                        score += 5
            
            entity_scores[entity] = score
        
        # Get highest scoring entity
        if entity_scores:
            top_entity = max(entity_scores, key=entity_scores.get)
            if entity_scores[top_entity] > 0:
                meta = self.ENTITY_KEYWORDS[top_entity]
                return top_entity, meta["column"], meta["group_by"]
        
        # Default to machine if unclear
        return "machine", "machine_id", ["machine_id", "machine_name"]
    
    def inject_entity_hint(self, user_query: str) -> str:
        """
        Generates a hint for SQL generation based on detected entity.
        """
        entity_name, column, group_by = self.detect_primary_entity(user_query)
        
        hint = (
            f"🎯 PRIMARY ENTITY DETECTED: '{entity_name.upper()}'\n"
            f"   - The user is asking WHICH {entity_name.upper()} (NOT which machine unless entity is machine)\n"
            f"   - MANDATORY: Use GROUP BY {', '.join(group_by)}\n"
            f"   - MANDATORY: Include {', '.join(group_by)} in SELECT clause\n"
            f"   - Filter by: {column}\n"
        )
        
        # Add specific warnings for common mistakes
        if entity_name == "grammage":
            hint += (
                f"   ⚠️  DO NOT return machine_id or machine_name as the answer!\n"
                f"   ⚠️  The result should be grammage values like 10.5, 20, 43, etc.\n"
            )
        elif entity_name == "loop":
            hint += (
                f"   ⚠️  DO NOT return machine_id or machine_name as the answer!\n"
                f"   ⚠️  The result should be loop_id values like 1, 2, 3, etc.\n"
            )
        elif entity_name == "variant":
            hint += (
                f"   ⚠️  DO NOT return machine_id or machine_name as the answer!\n"
                f"   ⚠️  The result should be variant names like 'Flat Cut', 'Ridge Cut', etc.\n"
            )
        
        return hint

# Example usage
if __name__ == "__main__":
    mapper = EntityMapper()
    
    test_queries = [
        "Which machine had the highest EGA on 2025-05-28?",
        "Which grammage produced the most good bags on 2025-06-03?",
        "Which loop had the lowest downtime on 2025-05-29?",
        "What variant had the best quality percentage?",
        "Which shift had the most wastage?"
    ]
    
    for query in test_queries:
        entity, column, group_by = mapper.detect_primary_entity(query)
        print(f"Query: {query}")
        print(f"  Entity: {entity}")
        print(f"  Column: {column}")
        print(f"  Group By: {group_by}")
        print()
        
        print("Generated Hint:")
        print(mapper.inject_entity_hint(query))
        print("=" * 80)
        print()
