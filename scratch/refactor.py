import os
import re

def combine_files(output_file, input_files):
    all_content = []
    imports = set()
    code_blocks = []
    
    for fpath in input_files:
        with open(fpath, "r") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith("import ") or line.startswith("from "):
                    if "database" not in line and "cache_and_memory" not in line \
                       and "sql_generation" not in line and "search_and_rag" not in line \
                       and "kpi_and_router" not in line and "validation" not in line \
                       and "log_stream" not in line and "analytics_and_alerts" not in line:
                        imports.add(line.strip())
                else:
                    code_blocks.append(line)
                    
    with open(output_file, "w") as f:
        f.write("\n".join(sorted(list(imports))))
        f.write("\n\n")
        # Write everything else
        for line in code_blocks:
            # Strip out log_streamer broadcast
            if "log_streamer" in line:
                continue
            line = re.sub(r"from search_and_rag import", "from core_engine import", line)
            f.write(line)

print("Starting refactor...")

# 1. data_layer.py
combine_files("data_layer.py", ["database.py", "cache_and_memory.py"])

# 2. core_engine.py
# For core engine, we need to be careful not to keep class definitions of the stripped items.
# A regex to remove a class definition and its body is hard, so we'll just write it as-is 
# and then remove the classes using a smart parse.

def remove_class(content, class_name):
    # Find "class ClassName" and remove until next top-level statement
    lines = content.split('\n')
    out = []
    in_class = False
    for line in lines:
        if line.startswith(f"class {class_name}"):
            in_class = True
            continue
        if in_class:
            if len(line.strip()) > 0 and not line.startswith(" ") and not line.startswith("\t") and not line.startswith("@"):
                in_class = False
            else:
                continue
        if not in_class:
            out.append(line)
    return '\n'.join(out)

# We will just concatenate for core_engine.py and then run remove_class
import sys
with open("search_and_rag.py", "r") as f:
    sar = f.read()
with open("kpi_and_router.py", "r") as f:
    kpi = f.read()
with open("sql_generation.py", "r") as f:
    sqlgen = f.read()

# We skip validation.py completely since SQLValidator is in there but we will just keep SQLValidator
with open("validation.py", "r") as f:
    val = f.read()

combined_core = sar + "\n" + kpi + "\n" + sqlgen + "\n" + val

# Strip unwanted classes
combined_core = remove_class(combined_core, "QuerySuggester")
combined_core = remove_class(combined_core, "ResultValidator")
combined_core = remove_class(combined_core, "EntityMapper")

# Remove log_streamer lines
combined_core = "\n".join([line for line in combined_core.split('\n') if "log_streamer" not in line])

# Replace imports in core_engine
combined_core = re.sub(r"from database import.*", "from data_layer import DatabaseConnector, SemanticLayer", combined_core)
combined_core = re.sub(r"from cache_and_memory import.*", "from data_layer import QueryCache, ConversationManager", combined_core)
combined_core = re.sub(r"from kpi_and_router import.*", "", combined_core)
combined_core = re.sub(r"from sql_generation import.*", "", combined_core)
combined_core = re.sub(r"from search_and_rag import.*", "", combined_core)
combined_core = re.sub(r"from validation import.*", "", combined_core)
combined_core = re.sub(r"from log_stream import.*", "", combined_core)

with open("core_engine.py", "w") as f:
    f.write(combined_core)

print("Created data_layer.py and core_engine.py")

# 3. Update app.py
with open("app.py", "r") as f:
    app_code = f.read()

# Replace imports
app_code = re.sub(r"from database import.*", "from data_layer import DatabaseConnector, SemanticLayer", app_code)
app_code = re.sub(r"from cache_and_memory import.*", "from data_layer import QueryCache, ConversationManager", app_code)
app_code = re.sub(r"from kpi_and_router import.*", "from core_engine import KPIEngine, QueryRouter", app_code)
app_code = re.sub(r"from sql_generation import.*", "from core_engine import SQLGenerator", app_code)
app_code = re.sub(r"from search_and_rag import.*", "from core_engine import TableSelector, RAGExplorer, PromptRAG", app_code)
app_code = re.sub(r"from analytics_and_alerts import.*", "", app_code)
app_code = re.sub(r"from validation import.*", "from core_engine import SQLValidator", app_code)
app_code = re.sub(r"from log_stream import.*", "", app_code)

# Remove Suggester usage
app_code = re.sub(r"suggester = QuerySuggester.*", "", app_code)
app_code = re.sub(r"suggestions = suggester.suggest_followups.*", "suggestions = []", app_code)

# Remove EntityMapper usage
app_code = re.sub(r"entity_mapper = EntityMapper.*", "", app_code)
app_code = re.sub(r"entity_hint = entity_mapper.*", "entity_hint = ''", app_code)

# Remove ResultValidator usage
app_code = re.sub(r"result_validator = ResultValidator.*", "", app_code)
app_code = re.sub(r"is_res_valid, res_warnings, corrected_res = result_validator.*", "is_res_valid, res_warnings, corrected_res = True, [], results", app_code)

# Remove analytics and alerts global vars
app_code = re.sub(r"analytics_engine: Optional\[AnalyticsEngine\] = None\n", "", app_code)
app_code = re.sub(r"alert_system: Optional\[AlertSystem\] = None\n", "", app_code)
app_code = re.sub(r", analytics_engine, \\?\n?\s*alert_system", "", app_code)
app_code = re.sub(r", analytics_engine", "", app_code)
app_code = re.sub(r", alert_system", "", app_code)

# Remove initialization
app_code = re.sub(r"analytics_engine = AnalyticsEngine.*", "", app_code)
app_code = re.sub(r"alert_system = AlertSystem.*", "", app_code)
app_code = re.sub(r"asyncio.create_task\(alert_system\.run_continuous_monitoring.*", "", app_code)

# Remove API logs
app_code = re.sub(r"@app.get\(\"/api/logs\"\).*?return StreamingResponse.*?text/event-stream\"\)", "", app_code, flags=re.DOTALL)

with open("app.py", "w") as f:
    f.write(app_code)

print("Updated app.py")

# Update index.html
with open("index.html", "r") as f:
    idx = f.read()
idx = re.sub(r"const logSource = new EventSource\('/api/logs'\);", "", idx)
idx = re.sub(r"logSource.onmessage = function\(event\) {.*?}", "", idx, flags=re.DOTALL)
with open("index.html", "w") as f:
    f.write(idx)

print("Updated index.html")
