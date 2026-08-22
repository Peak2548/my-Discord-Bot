@echo off
setlocal EnableDelayedExpansion

echo [INFO] Activating Virtual Environment...
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo [WARNING] venv folder not found! The bot will use the system's global Python.
)

REM Check if Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM 1. Upgrade pip to the latest version
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

REM 2. Force upgrade all required libraries (bypassing cache)
echo [INFO] Checking and upgrading libraries from requirements.txt...
pip install --no-cache-dir --upgrade -r "%~dp0requirements.txt"

REM Run the bot
echo [INFO] Starting Discord Bot...
python "%~dp0Main.py"

REM Auto-close when script finishes
echo [INFO] Bot has stopped. Closing...
timeout /t 2 >nul
exit /b 0