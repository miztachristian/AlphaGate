#!/bin/bash
# Quick Start Script for Trading App (Linux/Mac)

echo "======================================"
echo "Trading Strategy Analyzer"
echo "======================================"
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    echo ""
fi

echo "Activating virtual environment..."
source .venv/bin/activate
echo ""

echo "Installing dependencies..."
pip install -r requirements.txt
echo ""

echo "======================================"
echo "Setup Complete!"
echo "======================================"
echo ""
echo "Run the app with:"
echo "  python main.py --symbol BTC/USDT --timeframe 1h"
echo ""
echo "For help:"
echo "  python main.py --help"
echo ""
