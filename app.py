import json
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Body, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path

import os
from db_connector import DatabaseConnector
from kpi_engine import KPIEngine
from sql_generator import SQLGenerator
from router import QueryRouter
from table_selector import TableSelector
from rag_explorer import RAGExplorer
from query_cache import QueryCache
from analytics_engine import AnalyticsEngine
from query_suggester import QuerySuggester
from semantic_layer import SemanticLayer
from alert_system import AlertSystem
from conversation_manager import ConversationManager
from constraint_aware_query_generator import ConstraintAwareQueryGenerator
from nl_filter_parser import NLFilterParser
from backend.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
analytics_engine: Optional[AnalyticsEngine] = None
alert_system: Optional[AlertSystem] = None
semantic_layer: Optional[SemanticLayer] = None
conversation_manager = ConversationManager(max_history=20, max_turns=3)
query_generator: Optional[ConstraintAwareQueryGenerator] = None


# -----------------------------------------------------------------------
# Startup
# -----------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    global db_connector, active_schema, rag_explorer, analytics_engine, \
           alert_system, semantic_layer, query_generator, table_selector

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
        analytics_engine = AnalyticsEngine(connector)
        alert_system = AlertSystem(connector)
        query_generator = ConstraintAwareQueryGenerator(conversation_manager)

        # Build table selector once globally
        table_selector = TableSelector(active_schema)

        # Start continuous background monitoring
        asyncio.create_task(alert_system.run_continuous_monitoring(active_schema))

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
    global active_schema, table_selector, analytics_engine, alert_system, query_generator

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

        analytics_engine = AnalyticsEngine(db_connector)
        alert_system = AlertSystem(db_connector)
        query_generator = ConstraintAwareQueryGenerator(conversation_manager)

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
    return {"status": "disconnected"}


@app.post("/connect")
async def connect_database(req: ConnectRequest):
    global db_connector, active_schema, analytics_engine, alert_system, \
           semantic_layer, query_generator, table_selector

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
        analytics_engine = AnalyticsEngine(connector)
        alert_system = AlertSystem(connector)
        query_generator = ConstraintAwareQueryGenerator(conversation_manager)

        # Always reindex on connect — picks up any new tables automatically
        if table_selector is None:
            table_selector = TableSelector(active_schema)
        else:
            table_selector.refresh_schema(active_schema)

        # Restart monitoring with new schema
        asyncio.create_task(alert_system.run_continuous_monitoring(active_schema))

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
        suggester = QuerySuggester(active_schema)

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
                    suggestions = suggester.suggest_followups(req.query, sql, results, [])
                    
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
            suggestions = suggester.suggest_followups(req.query, "", {"row_count": 0, "rows": []}, [])
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
                from kpi_engine import TIME_COLUMN_MAP
                resolved_time_col = TIME_COLUMN_MAP.get(primary_tbl, "timestamp")

            # Parse temporal filters using NLFilterParser
            nl_parser = NLFilterParser()
            time_filter = nl_parser.parse_temporal_filter(req.query, time_column=resolved_time_col)
            if time_filter:
                enhanced_hints += f"\n\nPARSED TIME FILTER: {time_filter}\nUse this exact WHERE clause fragment for time filtering."

            # Pass matched_tables to sql_generator for confirmed table hint
            llm_generated_sql = await generator.generate_sql(
                req.query,
                reduced_schema,
                enhanced_hints,
                matched_tables=selected_tables
            )

            sql = query_generator.generate_query(
                req.query, active_schema, llm_generated_sql
            ) if query_generator else llm_generated_sql

            if sql != llm_generated_sql:
                logger.info(f"Constraint validator modified SQL:\nOriginal: {llm_generated_sql}\nModified: {sql}")

            yield format_sse("pipeline", {"stage": "sql_generation", "status": "completed"})

        except Exception as e:
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

            yield format_sse("pipeline", {
                "stage": "execution",
                "status": "completed",
                "sql": sql,
                "results": results
            })
        except Exception as e:
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
        if analytics_engine and selected_tables:
            try:
                from analytics_engine import METRIC_COLUMN_MAP, TIME_COLUMN_MAP as AE_TIME_MAP
                primary_table = selected_tables[0]
                metric_col = METRIC_COLUMN_MAP.get(primary_table)
                if metric_col:
                    time_col = AE_TIME_MAP.get(primary_table, "start_time")
                    auto_insights = await analytics_engine.auto_insights(
                        req.query, primary_table, metric_col, time_column=time_col
                    )
            except Exception as e:
                logger.warning(f"Auto insights failed: {e}")


        try:
            explanation = await generator.explain_results(
                req.query, sql, results, extra_context=extra_context
            )

            # Zero result suggestion
            row_count = results.get("row_count", 0)
            is_zero = row_count == 0 or (
                row_count == 1
                and results.get("rows")
                and list(results["rows"][0].values())[0] == 0
            )
            if is_zero and selected_tables:
                all_tables = [t["name"] for t in active_schema.get("tables", [])]
                alternatives = [t for t in all_tables if t not in selected_tables][:3]
                if alternatives:
                    explanation += (
                        f"\n\n💡 **Suggestion**: No results found in `{selected_tables[0]}`. "
                        f"You might want to check: {', '.join(f'`{t}`' for t in alternatives)}"
                    )

            if auto_insights:
                explanation += auto_insights

            result_summary = (
                str(results["rows"][0])
                if results.get("rows")
                else f"{row_count} rows"
            )
            conversation_manager.add_turn(req.session_id, req.query, sql, result_summary)
            await conversation_manager.add_assistant_message(
                explanation, sql_query=sql, query_result=results, session_id=req.session_id
            )

            suggestions = suggester.suggest_followups(req.query, sql, results, selected_tables)

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

@app.get("/alerts")
async def get_alerts():
    if not alert_system or not active_schema:
        return {"alerts": [], "message": "Alert system not initialized"}
    all_alerts = []
    for table in active_schema.get("tables", []):
        alerts = await alert_system.check_alerts(table.get("name"), time_window_minutes=60)
        all_alerts.extend(alerts)
    return {"alerts": all_alerts, "count": len(all_alerts)}


@app.get("/insights/{table_name}/{metric_column}")
async def get_insights(table_name: str, metric_column: str):
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    from kpi_engine import TIME_COLUMN_MAP
    time_col = TIME_COLUMN_MAP.get(table_name, "created_at")
    return {
        "table": table_name,
        "metric": metric_column,
        "anomalies": await analytics_engine.detect_anomalies(table_name, metric_column, time_column=time_col),
        "trends": await analytics_engine.detect_trends(table_name, metric_column, time_column=time_col),
        "time_patterns": await analytics_engine.analyze_time_patterns(table_name, metric_column, time_column=time_col)
    }


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
        from sql_generator import reload_prompts
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
