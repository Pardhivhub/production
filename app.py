import json
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Body, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

import os
from db_connector import DatabaseConnector
from kpi_engine import KPIEngine
from sql_generator import SQLGenerator
from router import QueryRouter
from table_selector import TableSelector
from rag_explorer import RAGExplorer
from conversation_memory import ConversationMemory
from query_cache import QueryCache
from analytics_engine import AnalyticsEngine
from query_suggester import QuerySuggester
from semantic_layer import SemanticLayer
from alert_system import AlertSystem
from nl_filter_parser import NLFilterParser
from backend.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Production Chatbot Engine",
    description="Streamlined Single-Page Industrial Chatbot API",
    version="2.0.0"
)

# CORS configuration
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
conversation_memory = ConversationMemory(max_turns=3)
query_cache = QueryCache(ttl_minutes=30)
analytics_engine: Optional[AnalyticsEngine] = None
alert_system: Optional[AlertSystem] = None
semantic_layer: Optional[SemanticLayer] = None

@app.on_event("startup")
async def startup_event():
    global db_connector, active_schema, rag_explorer, analytics_engine, alert_system, semantic_layer
    logger.info(f"Initializing auto-connection to default database: {settings.DATABASE_URL}")
    try:
        connector = DatabaseConnector(settings.DATABASE_URL)
        await connector.connect()
        raw_schema = await connector.get_schema_metadata()
        
        # Enrich schema with semantic layer
        semantic_layer = SemanticLayer(connector)
        active_schema = await semantic_layer.enrich_schema(raw_schema)
        
        db_connector = connector
        
        # Initialize analytics and alert systems
        analytics_engine = AnalyticsEngine(connector)
        alert_system = AlertSystem(connector)
        
        logger.info("Auto-connection to default database successful!")
        
        # Start background monitoring (optional - uncomment to enable)
        # asyncio.create_task(alert_system.run_continuous_monitoring(active_schema, interval_seconds=300))
        
    except Exception as e:
        logger.warning(f"Auto-connection to default database failed: {e}")

    try:
        rag_explorer = RAGExplorer()
        knowledge_dir = "./industrial_knowledge"
        if os.path.exists(knowledge_dir):
            logger.info(f"Indexing local knowledge docs from '{knowledge_dir}'...")
            rag_explorer.index_folder(knowledge_dir)
            logger.info("RAG documents indexed successfully!")
    except Exception as e:
        logger.warning(f"RAG initialization/indexing failed: {e}")

class ConnectRequest(BaseModel):
    db_url: str

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = "default"

def format_sse(event: str, data: dict) -> str:
    """Helper to structure event stream lines for Server-Sent Events."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the premium single-page chat dashboard."""
    try:
        with open("index.html", "r") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    except FileNotFoundError:
        try:
            with open("production/index.html", "r") as f:
                return HTMLResponse(content=f.read(), status_code=200)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="index.html dashboard template was not found.")

@app.post("/connect")
async def connect_database(req: ConnectRequest):
    """Establishes database connection dynamically and extracts schemas."""
    global db_connector, active_schema, analytics_engine, alert_system, semantic_layer
    db_url = req.db_url.strip() if req.db_url else settings.DATABASE_URL
    try:
        connector = DatabaseConnector(db_url)
        await connector.connect()
        
        raw_schema = await connector.get_schema_metadata()
        
        # Enrich with semantic layer
        semantic_layer = SemanticLayer(connector)
        schema_info = await semantic_layer.enrich_schema(raw_schema)
        
        db_connector = connector
        active_schema = schema_info
        
        # Initialize analytics and alerts
        analytics_engine = AnalyticsEngine(connector)
        alert_system = AlertSystem(connector)
        
        return {
            "status": "success",
            "message": "Successfully connected to database and loaded schema metadata.",
            "schema_info": schema_info
        }
    except Exception as e:
        logger.error(f"Connect endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def stream_chat(req: QueryRequest):
    """Streams spelling corrections, queries, tables, and answers via SSE."""
    global db_connector, active_schema
    
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
                    "message": "Please connect to a database using the connection panel at the top first.",
                    "suggestion": "Enter a valid SQLite path (e.g. 'itciot.db') or a PostgreSQL connection string to activate full analysis."
                })
        return StreamingResponse(fallback_stream(), media_type="text/event-stream")

    async def chat_event_generator():
        router = QueryRouter(active_schema)
        kpi_engine = KPIEngine(active_schema)
        table_selector = TableSelector(active_schema)
        generator = SQLGenerator(db_connector)
        suggester = QuerySuggester(active_schema)
        nl_parser = NLFilterParser()
        
        intent = router.classify_intent(req.query)
        if intent["type"] in ["greeting", "invalid_domain"]:
            yield format_sse("answer", {"answer": intent["response"]})
            return

        kpi_data = kpi_engine.compile_domain_hints(req.query)
        
        if kpi_data.get("corrections"):
            yield format_sse("spelling_correction", {"corrections": kpi_data["corrections"]})
            await asyncio.sleep(0.1)

        sql = ""
        selected_tables = []
        try:
            conv_context = conversation_memory.get_context(req.session_id)
            
            selected_tables_dict = table_selector.select_relevant_tables(req.query)
            selected_tables = [t["name"] for t in selected_tables_dict["tables"]]
            reduced_schema = {"tables": selected_tables_dict["tables"]}
            
            enhanced_hints = kpi_data["hints"]
            if conv_context:
                enhanced_hints = f"{conv_context}\n\n{enhanced_hints}"
            
            sql = await generator.generate_sql(req.query, reduced_schema, enhanced_hints)
            yield format_sse("pipeline", {"stage": "sql_generation", "status": "completed"})
        except Exception as e:
            yield format_sse("error", {
                "stage": "sql_generation",
                "error_type": "SQL Compiler Failure",
                "message": f"Could not formulate SQL statement: {str(e)}",
                "suggestion": "Try clarifying the metric name (e.g. specify 'overall efficiency' or 'excess give away %')."
            })
            return

        results = None
        try:
            cached_result = query_cache.get(sql)
            if cached_result:
                results = cached_result
                logger.info("Using cached query result")
            else:
                results = await db_connector.execute_query(sql)
                query_cache.set(sql, results)
            
            yield format_sse("pipeline", {
                "stage": "execution",
                "status": "completed",
                "sql": sql,
                "results": results
            })
        except Exception as e:
            yield format_sse("error", {
                "stage": "execution",
                "error_type": "Database Execution Error",
                "message": f"SQL execution failed: {str(e)}",
                "suggestion": "Double check if tables are correctly populated or schema columns are spelled correctly."
            })
            return

        extra_context = ""
        if rag_explorer:
            try:
                rag_hits = rag_explorer.retrieve(req.query, top_k=2)
                if rag_hits:
                    extra_context = "\n".join([f"[Source: {hit[0]}]\n{hit[1]}" for hit in rag_hits])
                    logger.info("Semantic context successfully retrieved from knowledge documents.")
            except Exception as e:
                logger.warning(f"Failed to retrieve semantic RAG context: {e}")
        
        auto_insights = ""
        if analytics_engine and selected_tables:
            try:
                metric_col = None
                for table_name in selected_tables:
                    table = next((t for t in active_schema.get("tables", []) if t["name"] == table_name), None)
                    if table:
                        for col in table.get("columns", []):
                            col_name = col.get("name", "").lower()
                            if any(m in col_name for m in ["weight", "speed", "cost", "level", "percent"]):
                                metric_col = col.get("name")
                                break
                    if metric_col:
                        break
                
                if metric_col:
                    auto_insights = await analytics_engine.auto_insights(req.query, selected_tables[0], metric_col)
            except Exception as e:
                logger.warning(f"Auto insights generation failed: {e}")

        try:
            explanation = await generator.explain_results(req.query, sql, results, extra_context=extra_context)
            
            if auto_insights:
                explanation += auto_insights
            
            result_summary = f"{results.get('row_count', 0)} rows returned"
            if results.get('rows') and len(results['rows']) > 0:
                result_summary = f"{results['rows'][0]}"
            conversation_memory.add_turn(req.session_id, req.query, sql, result_summary)
            
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
                "message": f"Failed to generate answer explanation: {str(e)}",
                "suggestion": "Your SQL was successful but the AI model is temporarily busy. Check the raw query results above."
            })

    return StreamingResponse(chat_event_generator(), media_type="text/event-stream")

@app.get("/alerts")
async def get_alerts():
    """Get current system alerts."""
    if not alert_system or not active_schema:
        return {"alerts": [], "message": "Alert system not initialized"}
    
    all_alerts = []
    for table in active_schema.get("tables", []):
        table_name = table.get("name")
        alerts = await alert_system.check_alerts(table_name, time_window_minutes=60)
        all_alerts.extend(alerts)
    
    return {"alerts": all_alerts, "count": len(all_alerts)}

@app.get("/insights/{table_name}/{metric_column}")
async def get_insights(table_name: str, metric_column: str):
    """Get analytics insights for a specific table and metric."""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    
    anomalies = await analytics_engine.detect_anomalies(table_name, metric_column)
    trends = await analytics_engine.detect_trends(table_name, metric_column)
    time_patterns = await analytics_engine.analyze_time_patterns(table_name, metric_column)
    
    return {
        "table": table_name,
        "metric": metric_column,
        "anomalies": anomalies,
        "trends": trends,
        "time_patterns": time_patterns
    }
