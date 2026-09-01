#!/bin/bash
# KumoCam launcher (macOS / Linux)
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    echo "First run: creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
echo "Checking dependencies..."
pip install -q -r requirements.txt
python -m kumocam.main
