# 🚀 Production Chatbot - Startup Guide

## Prerequisites

Before starting the application, ensure you have:

1. **Python 3.8+**
   ```bash
   python3 --version
   ```

2. **PostgreSQL running** (for database)
   ```bash
   brew services list | grep postgres
   # or
   brew services start postgresql
   ```

3. **Ollama running** (for LLM)
   ```bash
   # Check if Ollama is responding
   curl http://localhost:11434/api/tags
   # If not running, start it:
   # /Applications/Ollama.app/Contents/MacOS/Ollama
   ```

## Quick Start

### Option 1: Using the Startup Script (Recommended)

```bash
cd /Users/pardhivkrishna/Desktop/production/production
./START_APP.sh
```

Then open: **http://localhost:8000**

### Option 2: Manual Start

#### Step 1: Install Dependencies
```bash
pip3 install -r requirements.txt
```

#### Step 2: Start the Backend
```bash
python3 app.py
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

#### Step 3: Access the App
Open your browser to: **http://localhost:8000**

## 🔧 Configuration

The app uses settings from `/Users/pardhivkrishna/Desktop/production/production/backend/config.py`:

```python
LLM_PROVIDER: str = "ollama"
LLM_MODEL: str = "llama3.2:3b"
OLLAMA_BASE_URL: str = "http://localhost:11434"
DATABASE_URL: str = "postgresql://pardhivkrishna@localhost:5432/iiot_feedback"
```

### Override Settings with .env

Create a `.env` file in the production folder:

```
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2:3b
OLLAMA_BASE_URL=http://localhost:11434
DATABASE_URL=postgresql://pardhivkrishna@localhost:5432/iiot_feedback
```

## 🧪 Testing the Connection

### Test Database Connection
```bash
psql -h localhost -p 5432 -U pardhivkrishna -d iiot_feedback -c "SELECT COUNT(*) FROM ega_details_data;"
```

### Test Ollama Connection
```bash
curl -X POST http://localhost:11434/api/generate \
  -d '{"model": "llama3.2:3b", "prompt": "Hello", "stream": false}' \
  -H "Content-Type: application/json"
```

### Test API Status
```bash
curl http://localhost:8000/status
```

## 📋 Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Frontend Dashboard |
| `/status` | GET | Connection Status |
| `/connect` | POST | Connect to Database |
| `/chat` | POST | Send Query (Streaming) |
| `/alerts` | GET | Get Alerts |
| `/rules` | GET | Get All Rules |
| `/rules/prompt` | GET | Get System Prompt |

## 🐛 Troubleshooting

### Issue: "Network error / Connection refused"

**Solution 1:** Check Ollama is running
```bash
curl http://localhost:11434/api/tags
```

**Solution 2:** Check Database is running
```bash
psql -h localhost -U pardhivkrishna -d iiot_feedback -c "SELECT 1;"
```

**Solution 3:** Check port 8000 is not in use
```bash
lsof -i :8000
# Kill if needed
pkill -f "python3 app.py"
```

### Issue: "Database Not Connected"

**Solution:** Ensure PostgreSQL is running and the connection string is correct
```bash
# Check PostgreSQL status
brew services list | grep postgres

# Start PostgreSQL if needed
brew services start postgresql

# Verify connection
psql -h localhost -p 5432 -U pardhivkrishna -d iiot_feedback -c "SELECT 1;"
```

### Issue: "No rows returned" for grammage queries

**What actually exists in the database:**
- Grammage values: `100g`, `200g`, `250g` (not `10.5g`)
- Variants: Check with query below

**Check available data:**
```bash
psql -h localhost -p 5432 -U pardhivkrishna -d iiot_feedback -c "
SELECT DISTINCT 
  grammage, 
  variant, 
  DATE(start_time) as date
FROM ega_details_data 
LIMIT 10;"
```

## 🔄 Restarting the App

### Kill Backend Process
```bash
pkill -f "python3 app.py"
```

### Restart
```bash
cd /Users/pardhivkrishna/Desktop/production/production
python3 app.py
```

## 📊 Database Details

**Connection String:**
```
postgresql://pardhivkrishna@localhost:5432/iiot_feedback
```

**Available Tables:**
- `ega_details_data` - EGA metrics per machine/variant
- `oee_details_data` - OEE performance data
- `wastage_records` - Wastage and scrap logs
- `production_speed_details_data` - Production speeds
- `employees_list` - Employee data

## 💡 Testing Your Query

After the app is running, test the fixed query:

```bash
# Use the debug script to test your query
python3 debug_chatbot.py "which machine had the highest EGA percent on 2025-05-29 for the 10.5g Ridge Cut variant?"
```

This will show:
1. KPI engine analysis
2. Table selection
3. Generated SQL
4. Query results

## 🎯 Expected SQL (After Fixes)

Your query should generate:
```sql
SELECT machine_id FROM ega_details_data 
WHERE start_time::date = '2025-05-29' 
AND grammage = '100g'  -- Note: uses actual grammage values in database
AND variant = 'Flat Cut'  -- Note: uses actual variants
ORDER BY ega_percent DESC 
LIMIT 1
```

## 📝 Logs

Logs are written to:
- stdout during development
- Configure in `app.py` with `logging.basicConfig()`

For verbose output:
```bash
LOG_LEVEL=DEBUG python3 app.py
```

## 🎓 Learn More

- **API Documentation**: http://localhost:8000/docs (auto-generated by FastAPI)
- **ReDoc**: http://localhost:8000/redoc
- **Improvements Summary**: See `CHATBOT_IMPROVEMENTS_SUMMARY.md`
- **Fix Details**: See `FIXES_APPLIED.md`

---

**Ready to go!** 🚀
