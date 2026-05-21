@echo off
REM FILE: start.bat
REM One-click launcher for Windows

echo ==============================
echo   AI Second Brain - Starting
echo ==============================

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.11+
    pause
    exit /b 1
)

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install --quiet -r requirements.txt
    echo Dependencies installed.
) else (
    call venv\Scripts\activate.bat
)

python scripts\setup_env.py
python run.py %*
pause