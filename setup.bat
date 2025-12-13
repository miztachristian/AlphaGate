@echo off
REM Quick Start Script for Trading App

echo ======================================
echo Trading Strategy Analyzer
echo ======================================
echo.

REM Check if virtual environment exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    echo.
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat
echo.

echo Installing dependencies...
pip install -r requirements.txt
echo.

echo ======================================
echo Setup Complete!
echo ======================================
echo.
echo Run the app with:
echo   python main.py --symbol BTC/USDT --timeframe 1h
echo.
echo For help:
echo   python main.py --help
echo.

pause
