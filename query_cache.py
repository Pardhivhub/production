# query_cache.py
import logging
import hashlib
import json
from typing import Optional, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class QueryCache:
    """
    Simple in-memory cache for SQL query results.
    Caches based on SQL hash to avoid redundant database hits.
    """
    def __init__(self, ttl_minutes: int = 30):
        self.cache: Dict[str, Dict] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def _hash_sql(self, sql: str) -> str:
        """Generate hash key from SQL query."""
        return hashlib.md5(sql.encode()).hexdigest()
    
    def get(self, sql: str) -> Optional[Dict]:
        """Retrieve cached result if available and not expired."""
        key = self._hash_sql(sql)
        
        if key in self.cache:
            entry = self.cache[key]
            if datetime.now() - entry["timestamp"] < self.ttl:
                logger.info(f"Cache HIT for SQL hash {key[:8]}...")
                return entry["result"]
            else:
                # Expired, remove it
                del self.cache[key]
                logger.info(f"Cache EXPIRED for SQL hash {key[:8]}...")
        
        logger.info(f"Cache MISS for SQL hash {key[:8]}...")
        return None
    
    def set(self, sql: str, result: Dict):
        """Store query result in cache."""
        key = self._hash_sql(sql)
        self.cache[key] = {
            "result": result,
            "timestamp": datetime.now()
        }
        logger.info(f"Cached result for SQL hash {key[:8]}... (cache size: {len(self.cache)})")
    
    def clear(self):
        """Clear all cached entries."""
        self.cache.clear()
        logger.info("Query cache cleared")
    
    def cleanup_expired(self):
        """Remove expired entries from cache."""
        now = datetime.now()
        expired_keys = [
            key for key, entry in self.cache.items()
            if now - entry["timestamp"] >= self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
