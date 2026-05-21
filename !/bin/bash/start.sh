#!/bin/bash
# FILE: start.sh
# One-click launcher for Linux/Mac

echo "=============================="
echo "  AI Second Brain — Starting"
echo "=============================="

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

# Install deps if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet -r requirements.txt
    echo "Dependencies installed."
else
    source venv/bin/activate
fi

# Run setup
python3 scripts/setup_env.py

# Launch
python3 run.py "$@"