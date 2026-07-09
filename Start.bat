@echo off
setlocal EnableDelayedExpansion

REM เปิดใช้งาน Virtual Environment (venv) ก่อนรันบอท
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo [WARNING] ไม่พบโฟลเดอร์ venv บอทจะใช้ Python หลักของเครื่องแทน
)

REM Check if Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Run the bot with error handling and auto-close on completion
echo [INFO] Starting Discord Bot...
python "%~dp0MainBot.py"

REM Auto-close when script finishes (success or error)
echo [INFO] Bot has stopped. Closing...
timeout /t 2 >nul
exit /b 0