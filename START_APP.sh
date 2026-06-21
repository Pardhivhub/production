#!/bin/bash

# Start Backend and Frontend

echo "================================"
echo "Starting Production Chatbot App"
echo "================================"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install Python3."
    exit 1
fi

# Check if required packages are installed
echo "📦 Checking dependencies..."
pip3 install -q -r requirements.txt 2>/dev/null || echo "⚠️  Some dependencies may be missing"

# Kill any existing app.py processes
echo "🔄 Cleaning up old processes..."
pkill -f "python.*app.py" || true
sleep 1

# Start Backend
echo ""
echo "🚀 Starting Backend on http://localhost:8000"
echo "========================================"
python3 app.py &
BACKEND_PID=$!

# Wait for backend to start
sleep 3

# Check if backend started successfully
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "❌ Backend failed to start"
    exit 1
fi

echo "✅ Backend started (PID: $BACKEND_PID)"
echo ""
echo "================================"
echo "✅ APP IS RUNNING!"
echo "================================"
echo ""
echo "🌐 Frontend: http://localhost:8000"
echo "📊 API Status: http://localhost:8000/status"
echo "💬 Chat API: POST http://localhost:8000/chat"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Keep the script running
wait $BACKEND_PID
