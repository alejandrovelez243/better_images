#!/bin/bash
# Better Images — Run Script
# Sets up virtualenv and starts the Flask server

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  🖼️  Better Images — Setup & Launch"
echo "  ─────────────────────────────────────"

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "  📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate
source venv/bin/activate

# Install deps
echo "  📥 Installing dependencies..."
pip install -q -r requirements.txt

# Create dirs
mkdir -p uploads outputs models

# Run
echo ""
echo "  ✅ Ready! Opening http://localhost:5000"
echo ""
python app.py
