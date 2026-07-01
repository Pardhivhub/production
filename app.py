import json
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Body, Header, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path

import os
from data_layer import DatabaseConnector, SemanticLayer
from core_engine import KPIEngine, QueryRouter
from core_engine import SQLGenerator
from core_engine import TableSelector, RAGExplorer, PromptRAG
from data_layer import QueryCache, ConversationManager

from backend.config import settings
from core_engine import SQLValidator


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NLFilterParser:
    """
    Parses natural language date/time expressions from user queries and converts them
    into SQL WHERE clause fragments using the correct time column for each table.

    Supports:
    - Explicit date ranges: "from DD-MM-YYYY to DD-MM-YYYY", "from YYYY-MM-DD to YYYY-MM-DD"
    - Between ranges: "between 29-05-2025 and 31-05-2025"
    - Single dates: "on 29-05-2025", "on 2025-05-29", or bare dates like "29-05-2025"
    - Month-year: "May 2025", "in May 2025", "during April 2025"
    - Quarter: "Q1 2025", "Q2 2026"
    - Full year: "in 2025", "year 2025", "during 2025"
    - Relative: "today", "yesterday", "this week", "last week", "this month", "last month",
                "this year", "last year", "last 7 days", "last N days", "last N weeks",
                "last N months"
    """
    import re
    from datetime import datetime, timedelta

    _DATE_PATTERNS = [
        # DD-MM-YYYY range
        (r'from\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s+to\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})', 'range_dmy'),
        # YYYY-MM-DD range
        (r'from\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})', 'range_ymd'),
        # between X and Y (DMY)
        (r'between\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s+and\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})', 'range_dmy'),
        # between X and Y (YMD)
        (r'between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})', 'range_ymd'),
        # single date with "on"
        (r'on\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})', 'single_dmy'),
        (r'on\s+(\d{4}-\d{2}-\d{2})', 'single_ymd'),
    ]

    MONTH_MAP = {
        'january': 1, 'jan': 1,
        'february': 2, 'feb': 2,
        'march': 3, 'mar': 3,
        'april': 4, 'apr': 4,
        'may': 5,
        'june': 6, 'jun': 6,
        'july': 7, 'jul': 7,
        'august': 8, 'aug': 8,
        'september': 9, 'sep': 9, 'sept': 9,
        'october': 10, 'oct': 10,
        'november': 11, 'nov': 11,
        'december': 12, 'dec': 12,
    }

    def _parse_dmy(self, s):
        """Parse DD-MM-YYYY or DD/MM/YYYY string to datetime."""
        import re
        from datetime import datetime
        s = re.sub(r'[-/]', '-', s)
        return datetime.strptime(s, "%d-%m-%Y")

    def _parse_ymd(self, s):
        """Parse YYYY-MM-DD string to datetime."""
        from datetime import datetime
        return datetime.strptime(s, "%Y-%m-%d")

    def _is_unix(self, col):
        return "unix" in col.lower()

    def _to_sql(self, start, end, col):
        """Generate WHERE clause fragment for the given date range and time column."""
        from datetime import timedelta
        if self._is_unix(col):
            start_ts = int(start.timestamp())
            end_ts = int((end + timedelta(days=1)).timestamp()) - 1
            return f"{col} BETWEEN {start_ts} AND {end_ts}"
        else:
            return f"{col} BETWEEN '{start.strftime('%Y-%m-%d')}' AND '{end.strftime('%Y-%m-%d')} 23:59:59'"

    def parse_temporal_filter(self, query: str, time_column: str = "unix_timestamp") -> str:
        """
        Extract a time range from the query string and return a SQL WHERE fragment.
        Returns empty string if no temporal expression is found.
        """
        import re
        from datetime import datetime, timedelta
        import calendar

        q = query.lower().strip()
        now = datetime.now()

        # ── 1. Explicit date range and single date patterns ───────────────────────
        for pattern, kind in self._DATE_PATTERNS:
            m = re.search(pattern, q, re.IGNORECASE)
            if m:
                try:
                    if kind == 'range_dmy':
                        start = self._parse_dmy(m.group(1))
                        end = self._parse_dmy(m.group(2))
                    elif kind == 'range_ymd':
                        start = self._parse_ymd(m.group(1))
                        end = self._parse_ymd(m.group(2))
                    elif kind == 'single_dmy':
                        start = end = self._parse_dmy(m.group(1))
                    elif kind == 'single_ymd':
                        start = end = self._parse_ymd(m.group(1))
                    else:
                        continue
                    return self._to_sql(start, end, time_column)
                except Exception:
                    continue

        # ── 2. Standalone bare dates (no "on" keyword) ───────────────────────────
        # Try DD-MM-YYYY / DD/MM/YYYY first
        m = re.search(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b', q)
        if m:
            try:
                start = self._parse_dmy(m.group(1))
                return self._to_sql(start, start, time_column)
            except Exception:
                pass

        # Then try YYYY-MM-DD
        m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', q)
        if m:
            try:
                start = self._parse_ymd(m.group(1))
                return self._to_sql(start, start, time_column)
            except Exception:
                pass

        # ── 3. Quarter references ("Q1 2025", "q3 2026") ─────────────────────────
        m = re.search(r'\bq([1-4])\s*(\d{4})\b', q)
        if m:
            quarter = int(m.group(1))
            year = int(m.group(2))
            q_start_month = (quarter - 1) * 3 + 1
            q_end_month = q_start_month + 2
            start = datetime(year, q_start_month, 1)
            end = datetime(year, q_end_month, calendar.monthrange(year, q_end_month)[1])
            return self._to_sql(start, end, time_column)

        # ── 4. Named month + year ("May 2025", "in June 2025", "during April 2025") ─
        month_pattern = '|'.join(self.MONTH_MAP.keys())
        m = re.search(rf'\b({month_pattern})\s+(\d{{4}})\b', q)
        if m:
            month_num = self.MONTH_MAP[m.group(1)]
            year = int(m.group(2))
            last_day = calendar.monthrange(year, month_num)[1]
            start = datetime(year, month_num, 1)
            end = datetime(year, month_num, last_day)
            return self._to_sql(start, end, time_column)

        # ── 5. Full year reference ("in 2025", "year 2025", "during 2025") ────────
        m = re.search(r'\b(?:in|year|during|for)\s+(\d{4})\b', q)
        if m:
            year = int(m.group(1))
            if 2020 <= year <= 2030:
                return self._to_sql(datetime(year, 1, 1), datetime(year, 12, 31), time_column)

        # ── 6. Relative expressions ───────────────────────────────────────────────
        if 'today' in q:
            return self._to_sql(now.replace(hour=0, minute=0, second=0, microsecond=0), now, time_column)

        if 'yesterday' in q:
            y = now - timedelta(days=1)
            return self._to_sql(
                y.replace(hour=0, minute=0, second=0, microsecond=0),
                y.replace(hour=23, minute=59, second=59, microsecond=0),
                time_column
            )

        # last N days
        m = re.search(r'last\s+(\d+)\s+days?', q)
        if m:
            n = int(m.group(1))
            start = (now - timedelta(days=n)).replace(hour=0, minute=0, second=0, microsecond=0)
            return self._to_sql(start, now, time_column)

        # last N weeks
        m = re.search(r'last\s+(\d+)\s+weeks?', q)
        if m:
            n = int(m.group(1))
            start = (now - timedelta(weeks=n)).replace(hour=0, minute=0, second=0, microsecond=0)
            return self._to_sql(start, now, time_column)

        # last N months
        m = re.search(r'last\s+(\d+)\s+months?', q)
        if m:
            n = int(m.group(1))
            month = now.month - n
            year = now.year
            while month <= 0:
                month += 12
                year -= 1
            start = datetime(year, month, 1)
            return self._to_sql(start, now, time_column)

        if 'this week' in q:
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            return self._to_sql(start, now, time_column)

        if 'this month' in q:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return self._to_sql(start, now, time_column)

        if 'this year' in q or 'current year' in q:
            return self._to_sql(datetime(now.year, 1, 1), now, time_column)

        if 'last week' in q:
            start = now - timedelta(days=now.weekday() + 7)
            end = start + timedelta(days=6)
            return self._to_sql(
                start.replace(hour=0, minute=0, second=0, microsecond=0),
                end.replace(hour=23, minute=59, second=59, microsecond=0),
                time_column
            )

        if 'last month' in q:
            first_this = now.replace(day=1)
            end = first_this - timedelta(days=1)
            start = end.replace(day=1)
            return self._to_sql(
                start.replace(hour=0, minute=0, second=0, microsecond=0),
                end.replace(hour=23, minute=59, second=59, microsecond=0),
                time_column
            )

        if 'last year' in q or 'previous year' in q:
            return self._to_sql(datetime(now.year - 1, 1, 1), datetime(now.year - 1, 12, 31), time_column)

        return ""



# Initialize validators
sql_validator = SQLValidator()



app = FastAPI(
    title="Production Chatbot Engine",
    description="Streamlined Single-Page Industrial Chatbot API",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global connection variables
db_connector: Optional[DatabaseConnector] = None
active_schema: Optional[dict] = None
rag_explorer: Optional[RAGExplorer] = None
table_selector: Optional[TableSelector] = None
query_cache = QueryCache(ttl_minutes=30)
semantic_layer: Optional[SemanticLayer] = None
conversation_manager = ConversationManager(max_history=20, max_turns=3)


# -----------------------------------------------------------------------
# Startup
# -----------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    global db_connector, active_schema, rag_explorer, semantic_layer, table_selector

    logger.info(f"Auto-connecting to default database: {settings.DATABASE_URL}")
    try:
        connector = DatabaseConnector(settings.DATABASE_URL)
        await connector.connect()
        raw_schema = await connector.get_schema_metadata()

        semantic_layer = SemanticLayer(connector)
        active_schema = await semantic_layer.enrich_schema(raw_schema)

        db_connector = connector
        conversation_manager.db = connector
        await conversation_manager.initialize_db()
        query_cache.db = connector
        await query_cache.initialize_db()
        
        

        # Build table selector once globally
        table_selector = TableSelector(active_schema)

        # Start continuous background monitoring
        

        logger.info("Auto-connection successful!")
    except Exception as e:
        logger.warning(f"Auto-connection failed: {e}")

    try:
        rag_explorer = RAGExplorer()
        knowledge_dir = "./industrial_knowledge"
        if os.path.exists(knowledge_dir):
            logger.info("Indexing RAG knowledge docs...")
            rag_explorer.index_folder(knowledge_dir)
            logger.info("RAG indexed successfully!")
    except Exception as e:
        logger.warning(f"RAG init failed: {e}")


# -----------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------

class ConnectRequest(BaseModel):
    db_url: str

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = "default"


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _do_reindex() -> str:
    """
    Re-fetches schema from DB, re-enriches, re-indexes table selector.
    Called on /connect and on reindex chat command.
    Returns status message.
    """
    global active_schema, table_selector

    if not db_connector:
        return "No database connected. Please connect first."

    try:
        raw_schema = await db_connector.get_schema_metadata()
        semantic_layer.invalidate_cache()
        active_schema = await semantic_layer.enrich_schema(raw_schema)

        if table_selector is None:
            table_selector = TableSelector(active_schema)
        else:
            table_selector.refresh_schema(active_schema)

        
        

        table_count = len(active_schema.get("tables", []))
        table_names = [t["name"] for t in active_schema.get("tables", [])]
        logger.info(f"Reindex complete. {table_count} tables indexed: {table_names}")
        return (
            f"Schema reindexed successfully! "
            f"**{table_count} tables** are now available:\n"
            + "\n".join(f"- `{n}`" for n in table_names)
        )
    except Exception as e:
        logger.error(f"Reindex failed: {e}")
        return f"Reindex failed: {str(e)}"


# -----------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------

@app.get("/api/capabilities")
async def get_capabilities():
    import json
    import os
    cap_file = "config/capabilities.json"
    if os.path.exists(cap_file):
        with open(cap_file, "r") as f:
            return json.load(f)
    return []

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    for path in ["index.html", "production/index.html"]:
        try:
            with open(path, "r") as f:
                return HTMLResponse(content=f.read(), status_code=200)
        except FileNotFoundError:
            continue
    raise HTTPException(status_code=404, detail="index.html not found.")


@app.get("/status")
async def get_connection_status():
    if db_connector and active_schema:
        return {
            "status": "connected",
            "db_url": settings.DATABASE_URL,
            "schema_info": active_schema
        }
    return {
        "status": "disconnected",
        "default_db_url": settings.DATABASE_URL
    }


@app.post("/connect")
async def connect_database(req: ConnectRequest):
    global db_connector, active_schema, \
           semantic_layer, table_selector

    db_url = req.db_url.strip() if req.db_url else settings.DATABASE_URL
    try:
        connector = DatabaseConnector(db_url)
        await connector.connect()

        raw_schema = await connector.get_schema_metadata()
        semantic_layer = SemanticLayer(connector)
        schema_info = await semantic_layer.enrich_schema(raw_schema)

        db_connector = connector
        conversation_manager.db = connector
        await conversation_manager.initialize_db()
        query_cache.db = connector
        await query_cache.initialize_db()
        active_schema = schema_info
        
        

        # Always reindex on connect — picks up any new tables automatically
        if table_selector is None:
            table_selector = TableSelector(active_schema)
        else:
            table_selector.refresh_schema(active_schema)

        # Restart monitoring with new schema
        

        logger.info(f"Connected and reindexed: {len(active_schema.get('tables', []))} tables")

        return {
            "status": "success",
            "message": "Connected and schema reindexed.",
            "schema_info": schema_info
        }
    except Exception as e:
        logger.error(f"Connect error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
async def stream_chat(req: QueryRequest):
    global db_connector, active_schema, table_selector

    if not db_connector or not active_schema:
        router = QueryRouter({"tables": []})
        classification = router.classify_intent(req.query)

        async def fallback_stream():
            if classification["type"] == "greeting":
                yield format_sse("answer", {"answer": classification["response"]})
            else:
                yield format_sse("error", {
                    "stage": "connection",
                    "error_type": "Database Not Connected",
                    "message": "Please connect to a database first.",
                    "suggestion": "Enter a valid SQLite path or PostgreSQL connection string."
                })
        return StreamingResponse(fallback_stream(), media_type="text/event-stream")

    async def chat_event_generator():
        # ── GUARDRAILS: Block destructive / injection inputs ──────
        import re as _re
        _raw_q = req.query.strip()
        if len(_raw_q) > 2000:
            yield format_sse("answer", {"answer": "⚠️ Query is too long. Please keep questions under 2000 characters."})
            return
        _BLOCKED = _re.compile(
            r'\b(DROP|DELETE|TRUNCATE|UPDATE|INSERT|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b',
            _re.IGNORECASE
        )
        if _BLOCKED.search(_raw_q):
            yield format_sse("answer", {"answer": "⛔ That operation is not allowed. This assistant is read-only."})
            return
        _INJECTION = _re.compile(
            r'(ignore (previous|all) instructions?|you are now|pretend (you are|to be)|forget (everything|your instructions))',
            _re.IGNORECASE
        )
        if _INJECTION.search(_raw_q):
            yield format_sse("answer", {"answer": "⛔ I can only answer questions about your factory production data."})
            return
        # ── END GUARDRAILS ──────────────────────────────

        # Load persistent conversation history from DB
        await conversation_manager.load_history_from_db(req.session_id)

        # --- RECONSTRUCT PRONOUN / CONVERSATIONAL FOLLOW-UP QUERY ---
        q_norm = req.query.strip().lower().rstrip("?.!")

        
        # Extended list of follow-up triggers and simple indicators
        followup_phrases = {
            "yes", "yes explain", "explain why", "yes please", "explain this",
            "why", "explain", "sure", "ok", "okay", "please do", "go ahead",
            "why is this happening", "tell me why", "analyze", "analyze this",
            "do it", "please", "yes do it", "show me why", "tell me", "why?"
        }
        
        is_short_followup = len(q_norm.split()) <= 4 and (
            any(q_norm.startswith(word) for word in ["yes", "explain", "why", "analyze", "sure", "ok", "please"])
        )
        
        is_suggested_action = any(phrase in q_norm for phrase in [
            "analyze packaging inventory", "explain why this is happening", "analyze inventory levels"
        ])
        
        if q_norm in followup_phrases or is_short_followup or is_suggested_action:
            if req.session_id in conversation_manager.sessions and conversation_manager.sessions[req.session_id]:
                last_turn = conversation_manager.sessions[req.session_id][-1]
                prev_query = last_turn.get("query", "")
                if prev_query:
                    # Extract the original root query if it was already reconstructed
                    if "Context of previous query:" in prev_query:
                        root_query = prev_query.split("Context of previous query:")[-1].strip()
                    else:
                        root_query = prev_query
                        
                    reconstructed = f"{req.query}. Context of previous query: {root_query}"
                    logger.info(f"Reconstructed follow-up query: '{req.query}' -> '{reconstructed}'")
                    req.query = reconstructed

        await conversation_manager.add_user_message(req.query, session_id=req.session_id)


        router = QueryRouter(active_schema)
        kpi_engine = KPIEngine(active_schema)
        generator = SQLGenerator(db_connector)
        

        intent = router.classify_intent(req.query)

        # --- SEMANTIC QUERY CACHE LOOKUP ---
        if intent["type"] == "sql_query":
            try:
                cached_turn = await query_cache.get_semantic(req.query)
                if cached_turn:
                    sql = cached_turn["sql"]
                    results = cached_turn["results"]
                    
                    yield format_sse("pipeline", {
                        "stage": "table_selection",
                        "status": "completed",
                        "tables": [],
                        "scores": {}
                    })
                    yield format_sse("pipeline", {"stage": "sql_generation", "status": "completed"})
                    yield format_sse("pipeline", {
                        "stage": "execution",
                        "status": "completed",
                        "sql": sql,
                        "results": results
                    })
                    
                    explanation = await generator.explain_results(
                        req.query, sql, results, extra_context="[SEMANTIC CACHE HIT]"
                    )
                    suggestions = []
                    
                    conversation_manager.add_turn(req.session_id, req.query, sql, f"{results.get('row_count', 0)} rows")
                    await conversation_manager.add_assistant_message(
                        explanation, sql_query=sql, query_result=results, session_id=req.session_id
                    )
                    
                    yield format_sse("answer", {
                        "answer": explanation,
                        "sql": sql,
                        "results": results,
                        "suggestions": suggestions
                    })
                    return
            except Exception as e:
                logger.warning(f"Semantic cache lookup failed: {e}")

        # --- REINDEX COMMAND ---
        if intent["type"] == "reindex":
            status_msg = await _do_reindex()
            yield format_sse("answer", {"answer": status_msg})
            return

        # --- CLARIFICATION REQUEST ---
        if intent["type"] == "clarification":
            history = conversation_manager.get_conversation_context(last_n=1)
            if history:
                intent["type"] = "data_query"
            else:
                yield format_sse("clarification", {
                    "question": intent["question"],
                    "suggestions": intent["suggestions"],
                    "original_query": intent.get("original_query", req.query)
                })
                return

        # --- GREETING / INVALID DOMAIN ---
        if intent["type"] in ["greeting", "invalid_domain"]:
            yield format_sse("answer", {"answer": intent["response"]})
            return

        # --- CONCEPTUAL / RAG ---
        if intent["type"] == "conceptual":
            yield format_sse("pipeline", {"stage": "sql_generation", "status": "completed"})
            yield format_sse("pipeline", {
                "stage": "execution",
                "status": "completed",
                "sql": "-- RAG Conceptual Query",
                "results": {"columns": [], "rows": [], "row_count": 0}
            })
            rag_context = ""
            if rag_explorer and not settings.DISABLE_RAG:
                try:
                    rag_hits = rag_explorer.retrieve(req.query, top_k=2)
                    if rag_hits:
                        rag_context = "\n".join([f"[Source: {h[0]}]\n{h[1]}" for h in rag_hits])
                except Exception as e:
                    logger.warning(f"RAG retrieval failed: {e}")

            explanation = await generator.explain_rag_concept(req.query, rag_context)
            suggestions = []
            yield format_sse("answer", {"answer": explanation, "suggestions": suggestions})
            return

        # --- MAIN SQL PIPELINE ---
        kpi_data = kpi_engine.compile_domain_hints(req.query)

        if kpi_data.get("corrections"):
            yield format_sse("spelling_correction", {"corrections": kpi_data["corrections"]})
            await asyncio.sleep(0.1)

        sql = ""
        selected_tables = []

        try:
            conv_context = conversation_manager.get_context(req.session_id)
            full_context = conversation_manager.get_conversation_context(last_n=3)

            global table_selector
            if table_selector is None:
                table_selector = TableSelector(active_schema)

            # Use global table_selector — pass kpi matched_tables for scoring boost
            kpi_matched = kpi_data.get("matched_tables", [])
            selected_tables_dict = table_selector.select_relevant_tables(
                req.query,
                top_k=settings.MAX_TABLES_DEFAULT,
                kpi_matched_tables=kpi_matched
            )
            selected_tables = [t["name"] for t in selected_tables_dict["tables"]]
            scores = selected_tables_dict.get("scores", {})
            reduced_schema = {"tables": selected_tables_dict["tables"]}

            # Yield table selection stage completed with table scores for frontend rendering
            yield format_sse("pipeline", {
                "stage": "table_selection",
                "status": "completed",
                "tables": selected_tables,
                "scores": scores
            })
            await asyncio.sleep(0.05)

            enhanced_hints = kpi_data["hints"]
            
            # Inject entity detection hint BEFORE SQL generation
            entity_hint = ''
            enhanced_hints = f"{entity_hint}\n\n{enhanced_hints}"
            
            # Dynamically inject relationship join hints based on selected_tables!
            if len(selected_tables) > 1:
                join_hints = []
                for rel in kpi_engine.relationships:
                    from_t = rel["from_table"].split(".")[-1]
                    to_t = rel["to_table"].split(".")[-1]
                    if from_t in selected_tables and to_t in selected_tables:
                        join_hints.append(
                            f"- JOIN RELATIONSHIP DETECTED: To join '{from_t}' and '{to_t}', "
                            f"use: `JOIN {to_t} ON {from_t}.{rel['from_column']} = {to_t}.{rel['to_column']}` "
                            f"({rel['description']})."
                        )
                if join_hints:
                    enhanced_hints = f"{enhanced_hints}\n\n" + "\n".join(join_hints)

            if conv_context:
                enhanced_hints = f"{conv_context}\n\n{enhanced_hints}"
            if full_context:
                enhanced_hints = f"{full_context}\n\n{enhanced_hints}"

            # Resolve the time column name for the primary selected table
            resolved_time_col = "unix_timestamp"
            if selected_tables:
                primary_tbl = selected_tables[0]
                from core_engine import TIME_COLUMN_MAP
                resolved_time_col = TIME_COLUMN_MAP.get(primary_tbl, "timestamp")

            # Parse temporal filters using NLFilterParser
            nl_parser = NLFilterParser()
            time_filter = nl_parser.parse_temporal_filter(req.query, time_column=resolved_time_col)
            if time_filter:
                enhanced_hints += f"\n\nPARSED TIME FILTER: {time_filter}\nUse this exact WHERE clause fragment for time filtering."

            # Pass matched_tables to sql_generator for confirmed table hint
            llm_generated_sql, rules_meta_list = await generator.generate_sql(
                req.query,
                reduced_schema,
                enhanced_hints,
                matched_tables=selected_tables,
                time_filter=time_filter
            )

            if rules_meta_list:
                yield format_sse("pipeline", {
                    "stage": "rag_rules",
                    "rules": rules_meta_list
                })

            sql = llm_generated_sql

            if sql != llm_generated_sql:
                logger.info(f"Constraint validator modified SQL:\nOriginal: {llm_generated_sql}\nModified: {sql}")
            
            # ═══════════════════════════════════════════════════════════════
            # VALIDATE GENERATED SQL BEFORE EXECUTION
            # ═══════════════════════════════════════════════════════════════
            is_valid, sql_warnings, corrected_sql = sql_validator.validate(sql, req.query)
            
            if sql_warnings:
                logger.warning(f"SQL Validation Issues:\n" + "\n".join(sql_warnings))
                
                # Yield warnings so the frontend/test_runner can capture hallucinated columns
                yield format_sse("pipeline", {
                    "stage": "sql_validation",
                    "status": "warning",
                    "warnings": sql_warnings,
                    "fixes_applied": [w for w in sql_warnings if "AUTO-FIX" in w]
                })
                
                # If critical errors, use corrected SQL
                if not is_valid and corrected_sql != sql:
                    logger.info(f"Using auto-corrected SQL:\nOriginal: {sql}\nCorrected: {corrected_sql}")
                    sql = corrected_sql
                elif not is_valid and corrected_sql == sql:
                    # Critical error but no auto-fix could be applied!
                    # Trigger the LLM to self-heal
                    raise ValueError(f"SQL Validation Failed: " + " | ".join(sql_warnings))

            yield format_sse("pipeline", {"stage": "sql_generation", "status": "completed"})

        except Exception as e:
            # Yield raw SQL error for test runner before generating conversational fallback
            yield format_sse("sql_error", {"sql": sql if 'sql' in locals() else 'unknown', "error": str(e)})
            try:
                explanation = await generator.explain_error_conversational(req.query, str(e), "sql_generation")
                yield format_sse("answer", {"answer": explanation})
            except Exception:
                yield format_sse("error", {
                    "stage": "sql_generation",
                    "error_type": "SQL Compiler Failure",
                    "message": f"Could not formulate SQL: {str(e)}",
                    "suggestion": "Try clarifying the metric name."
                })
            return

        results = None
        try:
            results = await db_connector.execute_query(sql)
            await query_cache.set_semantic(req.query, sql, results)
            
            # ═══════════════════════════════════════════════════════════════
            # VALIDATE QUERY RESULTS FOR IMPOSSIBLE VALUES
            # ═══════════════════════════════════════════════════════════════
            query_type = "unknown"
            q_lower = req.query.lower()
            if "quality" in q_lower:
                query_type = "quality"
            elif "ega" in q_lower or "giveaway" in q_lower:
                query_type = "ega"
            elif "availability" in q_lower:
                query_type = "availability"
            
            result_rows = results.get("rows", [])
            if result_rows:
                is_result_valid, result_warnings, filtered_rows = result_validator.validate_results(
                    result_rows, query_type
                )
                
                if result_warnings:
                    logger.warning(f"Result Validation Issues:\n" + "\n".join(result_warnings))
                    
                    # If corrupt data detected, use filtered results
                    if not is_result_valid and len(filtered_rows) < len(result_rows):
                        logger.info(f"Filtered {len(result_rows) - len(filtered_rows)} corrupt rows")
                        results["rows"] = filtered_rows
                        results["row_count"] = len(filtered_rows)
                        
                        yield format_sse("pipeline", {
                            "stage": "result_validation",
                            "status": "filtered",
                            "warnings": result_warnings,
                            "original_count": len(result_rows),
                            "filtered_count": len(filtered_rows)
                        })

            yield format_sse("pipeline", {
                "stage": "execution",
                "status": "completed",
                "sql": sql,
                "results": results
            })
        except Exception as e:
            # Yield raw SQL error for test runner before generating conversational fallback
            yield format_sse("sql_error", {"sql": sql, "error": str(e)})
            try:
                explanation = await generator.explain_error_conversational(req.query, str(e), "execution")
                yield format_sse("answer", {"answer": explanation})
            except Exception:
                yield format_sse("error", {
                    "stage": "execution",
                    "error_type": "Database Execution Error",
                    "message": f"SQL execution failed: {str(e)}",
                    "suggestion": "Check if tables are populated and column names are correct."
                })
            return

        extra_context = ""
        if rag_explorer and not settings.DISABLE_RAG:
            try:
                rag_hits = rag_explorer.retrieve(req.query, top_k=2)
                if rag_hits:
                    extra_context = "\n".join([f"[Source: {h[0]}]\n{h[1]}" for h in rag_hits])
            except Exception as e:
                logger.warning(f"RAG retrieval failed: {e}")

        auto_insights = ""
        # Auto insights disabled based on user preference


        try:
            explanation = await generator.explain_results(
                req.query, sql, results, extra_context=extra_context
            )

            # Zero result suggestion and auto insights are disabled

            result_summary = (
                str(results["rows"][0])
                if results.get("rows")
                else f"{results.get('row_count', 0)} rows"
            )
            conversation_manager.add_turn(req.session_id, req.query, sql, result_summary)
            await conversation_manager.add_assistant_message(
                explanation, sql_query=sql, query_result=results, session_id=req.session_id
            )

            suggestions = []

            yield format_sse("answer", {
                "answer": explanation,
                "sql": sql,
                "results": results,
                "suggestions": suggestions
            })

        except Exception as e:
            yield format_sse("error", {
                "stage": "explanation",
                "error_type": "Explainer Generation Error",
                "message": f"Explanation failed: {str(e)}",
                "suggestion": "SQL ran successfully. Check raw results above."
            })

    return StreamingResponse(chat_event_generator(), media_type="text/event-stream")


# -----------------------------------------------------------------------
# Other Endpoints
# -----------------------------------------------------------------------



@app.get("/report")
async def generate_shift_report(shift: str, date: str):
    if not db_connector:
        raise HTTPException(status_code=503, detail="Database not connected")
        
    catalog = load_catalog()
    shifts_def = catalog.get("shifts", {})
    shift_key = None
    for k, s_def in shifts_def.items():
        if shift.lower() == k.lower() or shift.lower() in [a.lower() for a in s_def.get("aliases", [])]:
            shift_key = k
            break
            
    if not shift_key:
        raise HTTPException(status_code=400, detail=f"Invalid shift name: {shift}")
        
    s_def = shifts_def[shift_key]
    start_time_str = s_def["start"]
    end_time_str = s_def["end"]
    
    from datetime import datetime, timedelta
    try:
        report_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
        
    start_ts = datetime.combine(report_date, datetime.strptime(start_time_str, "%H:%M:%S").time())
    if end_time_str < start_time_str:
        end_ts = datetime.combine(report_date + timedelta(days=1), datetime.strptime(end_time_str, "%H:%M:%S").time())
    else:
        end_ts = datetime.combine(report_date, datetime.strptime(end_time_str, "%H:%M:%S").time())
        
    # Format for SQL queries
    start_ts_str = start_ts.strftime("%Y-%m-%d %H:%M:%S")
    end_ts_str = end_ts.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        oee_query = f"""
            SELECT 
                COALESCE(SUM(downtime_mins), 0) AS total_downtime,
                COALESCE(SUM(good_bags), 0) AS total_good_bags,
                COALESCE(SUM(failed_bags), 0) AS total_failed_bags,
                COALESCE(SUM(empty_bags), 0) AS total_empty_bags,
                COALESCE(SUM(overlimit_count), 0) AS total_overlimit,
                COALESCE(SUM(1), 0) AS total_hours,
                COALESCE(AVG(target_speed), 0) AS avg_target_speed
            FROM oee_details_data
            WHERE start_time >= '{start_ts_str}' AND start_time < '{end_ts_str}'
        """
        
        ega_query = f"""
            SELECT COALESCE(AVG(ega_percent), 0) AS avg_ega
            FROM ega_details_data
            WHERE start_time >= '{start_ts_str}' AND start_time < '{end_ts_str}'
        """
        
        wastage_query = f"""
            SELECT COALESCE(SUM(wastage_kg), 0) AS total_wastage
            FROM wastage_records
            WHERE shift ILIKE '%{shift_key}%' 
               OR (production_start_time >= '{start_ts_str}' AND production_start_time < '{end_ts_str}')
        """
        
        top_downtime_query = f"""
            SELECT 
                o.machine_id,
                COALESCE(m.machine_name, 'Machine-' || o.machine_id) AS machine_name,
                SUM(o.downtime_mins) AS downtime
            FROM oee_details_data o
            LEFT JOIN machines m ON o.machine_id = m.id
            WHERE o.start_time >= '{start_ts_str}' AND o.start_time < '{end_ts_str}'
            GROUP BY o.machine_id, m.machine_name
            ORDER BY downtime DESC
            LIMIT 3
        """
        
        top_failed_query = f"""
            SELECT 
                o.machine_id,
                COALESCE(m.machine_name, 'Machine-' || o.machine_id) AS machine_name,
                SUM(o.failed_bags) AS failed_bags
            FROM oee_details_data o
            LEFT JOIN machines m ON o.machine_id = m.id
            WHERE o.start_time >= '{start_ts_str}' AND o.start_time < '{end_ts_str}'
            GROUP BY o.machine_id, m.machine_name
            ORDER BY failed_bags DESC
            LIMIT 3
        """

        results = await asyncio.gather(
            db_connector.execute_query(oee_query),
            db_connector.execute_query(ega_query),
            db_connector.execute_query(wastage_query),
            db_connector.execute_query(top_downtime_query),
            db_connector.execute_query(top_failed_query)
        )
        
        oee_res = results[0].get("rows", [{}])[0]
        ega_res = results[1].get("rows", [{}])[0]
        wastage_res = results[2].get("rows", [{}])[0]
        top_downtime = results[3].get("rows", [])
        top_failed = results[4].get("rows", [])
        
        # OEE Calculations
        h = oee_res.get("total_hours", 0)
        dt = oee_res.get("total_downtime", 0)
        gb = oee_res.get("total_good_bags", 0)
        fb = oee_res.get("total_failed_bags", 0)
        ol = oee_res.get("total_overlimit", 0)
        ts = oee_res.get("avg_target_speed", 0)
        
        availability = 0.0
        performance = 0.0
        quality = 0.0
        oee = 0.0
        
        if h > 0:
            total_mins = h * 60
            run_mins = total_mins - dt
            availability = max(0.0, (run_mins / total_mins) * 100)
            
            if run_mins > 0 and ts > 0:
                performance = min(100.0, ((gb / run_mins) / ts) * 100)
            
            if gb > 0:
                quality = max(0.0, (100 - ((ol + fb) / gb) * 100))
                
            oee = (availability * performance * quality) / 10000
            
        return {
            "shift": shift_key,
            "label": s_def.get("label", shift),
            "date": date,
            "start_time": start_ts_str,
            "end_time": end_ts_str,
            "metrics": {
                "oee_percent": round(oee, 2),
                "availability_percent": round(availability, 2),
                "performance_percent": round(performance, 2),
                "quality_percent": round(quality, 2),
                "total_downtime_mins": round(dt, 2),
                "total_good_bags": int(gb),
                "total_failed_bags": int(fb),
                "total_empty_bags": int(oee_res.get("total_empty_bags", 0)),
                "avg_ega_percent": round(ega_res.get("avg_ega", 0), 2),
                "total_wastage_kg": round(wastage_res.get("total_wastage", 0), 2)
            },
            "top_downtime_machines": top_downtime,
            "top_failed_machines": top_failed
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate shift report: {str(e)}")


@app.get("/conversation/status")
async def get_conversation_status():
    return conversation_manager.get_summary()


@app.post("/conversation/clear")
async def clear_conversation():
    conversation_manager.clear_all_constraints()
    return {"status": "success", "message": "Conversation constraints cleared"}


@app.post("/clear_cache")
async def clear_cache():
    query_cache.clear()
    if query_cache.db and query_cache.db_initialized:
        try:
            if query_cache.vector_enabled:
                await query_cache.db.execute_write("TRUNCATE TABLE semantic_query_cache")
            else:
                await query_cache.db.execute_write("TRUNCATE TABLE semantic_query_cache")
        except Exception as e:
            logger.error(f"Failed to clear semantic cache DB: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    return {"status": "success", "message": "Cache cleared successfully."}


@app.get("/conversation/history")
async def get_conversation_history():
    return {
        "context": conversation_manager.get_conversation_context(last_n=10),
        "active_constraints": conversation_manager.get_active_constraints()
    }


# ── Rules Manager ────────────────────────────────────────

KPI_CATALOG_PATH = Path(__file__).parent / "config" / "kpi_catalog.json"

def load_catalog():
    with open(KPI_CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_catalog(catalog: dict):
    with open(KPI_CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)

class KPIFormula(BaseModel):
    metric: str
    aliases: List[str]
    table: str
    formula: str
    query: str
    time_column: Optional[str] = "timestamp"
    groupable_by: Optional[List[str]] = []
    filters: Optional[List[str]] = []

class ShiftPattern(BaseModel):
    name: str
    start: str
    end: str
    label: str
    aliases: List[str]

class RelationshipRule(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    description: str

class ExcludeWord(BaseModel):
    word: str

@app.get("/rules")
async def get_all_rules():
    catalog = load_catalog()
    return {
        "formulas": catalog.get("formulas", {}),
        "shifts": catalog.get("shifts", {}),
        "relationships": catalog.get("relationships", []),
        "domain_hints": catalog.get("domain_hints", {}),
        "exclude_column_words": catalog.get("exclude_column_words", [])
    }

class PromptData(BaseModel):
    content: str

@app.get("/rules/prompt")
async def get_system_prompt():
    prompt_path = Path(__file__).parent / "prompts" / "sql_system.txt"
    try:
        content = prompt_path.read_text(encoding="utf-8")
        return {"content": content}
    except Exception as e:
        return {"content": f"Error loading prompt: {e}"}

@app.post("/rules/prompt")
async def update_system_prompt(data: PromptData):
    prompt_path = Path(__file__).parent / "prompts" / "sql_system.txt"
    try:
        prompt_path.write_text(data.content, encoding="utf-8")
        from core_engine import reload_prompts
        reload_prompts()
        return {"status": "success", "message": "Prompt updated and AI reloaded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rules/formula")
async def add_formula(formula: KPIFormula):
    catalog = load_catalog()
    catalog.setdefault("formulas", {})[formula.metric] = {
        "metric": formula.metric,
        "aliases": formula.aliases,
        "type": "stored_kpi",
        "table": formula.table,
        "formula": formula.formula,
        "query": formula.query,
        "time_column": formula.time_column,
        "groupable_by": formula.groupable_by,
        "filters": formula.filters
    }
    save_catalog(catalog)
    global active_schema
    if active_schema:
        await _do_reindex()
    return {"status": "success", "message": f"Formula {formula.metric} added"}

@app.put("/rules/formula/{metric_name}")
async def update_formula(metric_name: str, formula: KPIFormula):
    catalog = load_catalog()
    if metric_name not in catalog.get("formulas", {}):
        raise HTTPException(status_code=404, detail="Formula not found")
    catalog["formulas"][metric_name] = {
        "metric": formula.metric,
        "aliases": formula.aliases,
        "type": "stored_kpi",
        "table": formula.table,
        "formula": formula.formula,
        "query": formula.query,
        "time_column": formula.time_column,
        "groupable_by": formula.groupable_by,
        "filters": formula.filters
    }
    save_catalog(catalog)
    global active_schema
    if active_schema:
        await _do_reindex()
    return {"status": "success", "message": f"Formula {metric_name} updated"}

@app.delete("/rules/formula/{metric_name}")
async def delete_formula(metric_name: str):
    catalog = load_catalog()
    if metric_name not in catalog.get("formulas", {}):
        raise HTTPException(status_code=404, detail="Formula not found")
    del catalog["formulas"][metric_name]
    save_catalog(catalog)
    global active_schema
    if active_schema:
        await _do_reindex()
    return {"status": "success", "message": f"Formula {metric_name} deleted"}

@app.post("/rules/shift")
async def add_shift(shift: ShiftPattern):
    catalog = load_catalog()
    catalog.setdefault("shifts", {})[shift.name] = {
        "start": shift.start,
        "end": shift.end,
        "label": shift.label,
        "aliases": shift.aliases
    }
    save_catalog(catalog)
    global active_schema
    if active_schema:
        await _do_reindex()
    return {"status": "success", "message": f"Shift {shift.name} added"}

@app.delete("/rules/shift/{shift_name}")
async def delete_shift(shift_name: str):
    catalog = load_catalog()
    if shift_name not in catalog.get("shifts", {}):
        raise HTTPException(status_code=404, detail="Shift not found")
    del catalog["shifts"][shift_name]
    save_catalog(catalog)
    global active_schema
    if active_schema:
        await _do_reindex()
    return {"status": "success", "message": f"Shift {shift_name} deleted"}

@app.post("/rules/relationship")
async def add_relationship(rel: RelationshipRule):
    catalog = load_catalog()
    catalog.setdefault("relationships", []).append({
        "from_table": rel.from_table,
        "from_column": rel.from_column,
        "to_table": rel.to_table,
        "to_column": rel.to_column,
        "description": rel.description
    })
    save_catalog(catalog)
    global active_schema
    if active_schema:
        await _do_reindex()
    return {"status": "success", "message": "Relationship added"}

@app.delete("/rules/relationship")
async def delete_relationship(from_table: str, from_column: str, to_table: str, to_column: str):
    catalog = load_catalog()
    rels = catalog.get("relationships", [])
    new_rels = [
        r for r in rels
        if not (
            r.get("from_table") == from_table and
            r.get("from_column") == from_column and
            r.get("to_table") == to_table and
            r.get("to_column") == to_column
        )
    ]
    if len(new_rels) == len(rels):
        raise HTTPException(status_code=404, detail="Relationship not found")
    catalog["relationships"] = new_rels
    save_catalog(catalog)
    global active_schema
    if active_schema:
        await _do_reindex()
    return {"status": "success", "message": "Relationship deleted"}

@app.post("/rules/exclude-word")
async def add_exclude_word(item: ExcludeWord):
    catalog = load_catalog()
    words = catalog.get("exclude_column_words", [])
    if item.word not in words:
        words.append(item.word)
        catalog["exclude_column_words"] = words
        save_catalog(catalog)
        global active_schema
        if active_schema:
            await _do_reindex()
    return {"status": "success", "message": f"Word '{item.word}' excluded"}

@app.delete("/rules/exclude-word/{word}")
async def remove_exclude_word(word: str):
    catalog = load_catalog()
    words = catalog.get("exclude_column_words", [])
    if word in words:
        words.remove(word)
        catalog["exclude_column_words"] = words
        save_catalog(catalog)
        global active_schema
        if active_schema:
            await _do_reindex()
    return {"status": "success", "message": f"Word '{word}' removed from exclude list"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
