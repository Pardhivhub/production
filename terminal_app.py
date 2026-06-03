import asyncio
import json
import logging
import os
from backend.config import settings
from db_connector import DatabaseConnector
from kpi_engine import KPIEngine
from sql_generator import SQLGenerator
from router import QueryRouter
from table_selector import TableSelector
from rag_explorer import RAGExplorer
from conversation_manager import ConversationManager
from query_cache import QueryCache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    print("🤖 Manufacturing Database Chatbot (Terminal Mode)")
    print("=" * 50)
    
    default_db = settings.DATABASE_URL
    print(f"\nDefault Database Link: {default_db}")
    db_url = input("Enter database URL (or press ENTER to use default): ").strip()
    if not db_url:
        db_url = default_db
        
    connector = DatabaseConnector(db_url)
    await connector.connect()
    schema = await connector.get_schema_metadata()
    print(f"\n✅ Connected! Found {len(schema.get('tables', []))} tables.")
    for t in schema.get('tables', []):
        col_preview = ", ".join(c['name'] for c in t.get('columns', [])[:5])
        print(f"   📋 {t['name']} ({col_preview}...)")

    selector = TableSelector(schema)
    router = QueryRouter(schema)
    kpi = KPIEngine(schema)
    generator = SQLGenerator(connector)
    rag = RAGExplorer()
    
    # Initialize conversation manager and cache for terminal session
    conversation_memory = ConversationManager(max_turns=3)
    query_cache = QueryCache(ttl_minutes=30)

    # Index custom knowledge folder if present
    knowledge_dir = "./industrial_knowledge"
    if os.path.exists(knowledge_dir):
        print(f"⚙️  Indexing local knowledge docs from '{knowledge_dir}'...")
        rag.index_folder(knowledge_dir)
        print("✅ Indexing completed!")

    print("\nType your question (or 'quit' to exit)")
    print("=" * 50)
    
    session_id = "terminal_session"
    
    while True:
        query = input("\n❓ You: ").strip()
        if query.lower() in ("quit", "exit", "q"):
            print("👋 Goodbye!")
            break

        if not query:
            continue

        # --- RECONSTRUCT PRONOUN / CONVERSATIONAL FOLLOW-UP QUERY ---
        q_norm = query.strip().lower().rstrip("?.!")
        
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
            if session_id in conversation_memory.sessions and conversation_memory.sessions[session_id]:
                last_turn = conversation_memory.sessions[session_id][-1]
                prev_query = last_turn.get("query", "")
                if prev_query:
                    # Extract the original root query if it was already reconstructed
                    if "Context of previous query:" in prev_query:
                        root_query = prev_query.split("Context of previous query:")[-1].strip()
                    else:
                        root_query = prev_query
                        
                    reconstructed = f"{query}. Context of previous query: {root_query}"
                    logger.info(f"Reconstructed follow-up query: '{query}' -> '{reconstructed}'")
                    query = reconstructed

        intent = router.classify_intent(query)
        if intent["type"] in ("greeting", "invalid_domain"):
            print(f"🤖 {intent['response']}")
            continue

        # Compile KPI hints & corrections
        kpi_data = kpi.compile_domain_hints(query)
        if kpi_data.get("corrections"):
            print(f"🔧 Corrections: {kpi_data['corrections']}")

        # Retrieve conversation history context for follow-up query accuracy
        conv_context = conversation_memory.get_context(session_id)

        kpi_matched = kpi_data.get("matched_tables", [])
        selected = selector.select_relevant_tables(
            query,
            top_k=3,
            kpi_matched_tables=kpi_matched
        )
        reduced_schema = {"tables": selected["tables"]}

        # Retrieve any semantic documentation context via RAG
        rag_hits = rag.retrieve(query, top_k=2)
        extra_context = ""
        if rag_hits:
            extra_context = "\n".join([f"[Source: {hit[0]}]\n{hit[1]}" for hit in rag_hits])
            print("🔎 Semantic context retrieved from knowledge documents.")

        try:
            enhanced_hints = kpi_data.get("hints", "")
            if conv_context:
                enhanced_hints = f"{conv_context}\n\n{enhanced_hints}"

            # Step 1: SQL Generation
            sql = await generator.generate_sql(query, reduced_schema, enhanced_hints)
            print(f"📝 Generated SQL: {sql}")
            
            # Step 2: SQL Execution (with caching)
            cached_result = query_cache.get(sql)
            if cached_result:
                print("⚡ [Cache Hit] Retrieving results from memory cache...")
                results = cached_result
            else:
                results = await connector.execute_query(sql)
                query_cache.set(sql, results)
                
            rows = results.get("rows", [])
            print(f"\n📊 Results ({results.get('row_count', 0)} rows):")
            for row in rows[:10]:
                print(f"   {row}")
                
            # Step 3: Natural Language Explanation
            explanation = await generator.explain_results(query, sql, results, extra_context=extra_context)
            print(f"\n🤖 Explanation: {explanation}")
            
            # Store turn in conversation memory
            conversation_memory.add_turn(
                session_id, 
                query, 
                sql, 
                f"{results.get('row_count', 0)} rows returned (first row sample: {rows[0] if rows else 'None'})"
            )
            
        except Exception as e:
            # Fallback to direct general LLM response using RAG if SQL path fails (e.g. non-database question)
            logger.warning(f"SQL Generation/Execution path bypassed or failed: {e}. Answering using context documents.")
            try:
                explanation = await generator.explain_results(query, "N/A (Knowledge Query)", {"rows": []}, extra_context=extra_context)
                print(f"\n🤖 Answer: {explanation}")
            except Exception as explain_err:
                print(f"❌ Error: {e} (Fallback also failed: {explain_err})")

if __name__ == "__main__":
    asyncio.run(main())
