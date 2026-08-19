@echo off
setlocal

REM 1. Start PO Token Server via node build/main.js with no separate window
REM    Use "start /B" instead of "start /MIN cmd /c ..." because /B binds the
REM    process to this console window (no new window/console opened). Result:
REM      - No window appears at all (not even minimized)
REM      - Closing this Start.bat window (X or Ctrl+C) kills the node process
REM        automatically since Windows closes processes sharing the same console
echo [INFO] Starting bgutil PO Token Server on port 4416 (hidden)...
pushd "%~dp0bgutil-ytdlp-pot-provider\server"
start /B "" node build/main.js >nul 2>&1
popd

REM Wait 5 seconds for the server to finish starting
timeout /t 5 >nul

REM 2. Activate Virtual Environment (venv) before running the bot
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo [WARNING] venv folder not found — bot will use the system Python instead
)

REM Check if Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.11+ from https://python.org
    pause
    goto :cleanup
)

REM Check and update dependencies
if exist "%~dp0requirements.txt" (
    echo [INFO] Checking and updating dependencies...
    python -m pip install --upgrade -r "%~dp0requirements.txt"
    python.exe -m pip install --upgrade pip
) else (
    echo [WARNING] requirements.txt not found! Skipping dependency update.
)

REM Check for cookies.txt (needed for YouTube playback to bypass 403s)
if not exist "%~dp0cookies.txt" (
    echo.
    echo [WARNING] cookies.txt not found next to this file.
    echo [WARNING] YouTube music playback ^(^!play^) will likely fail with 403 errors.
    echo [WARNING] Export cookies.txt from a browser logged into YouTube ^(e.g. the
    echo [WARNING] "Get cookies.txt LOCALLY" extension^) and place it in this folder:
    echo [WARNING]   %~dp0cookies.txt
    echo [WARNING] Continuing to start the bot anyway - other commands will still work.
    echo.
)

REM Run the bot with error handling and auto-close on completion
echo [INFO] Starting Discord Bot...
python "%~dp0MainBot.py"

REM Auto-close when script finishes (success or error)
echo [INFO] Bot has stopped. Cleaning up and closing...

:cleanup
REM 3. Double-check kill PO Token Server in case bot stopped normally (this window
REM    is still open, only the script finished). Target only node.exe running
REM    build/main.js — do not touch other node.exe instances on the machine.
powershell -NoProfile -Command "Get-CimInstance -ClassName Win32_Process | Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -like '*build*main.js*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

timeout /t 2 >nul
exit /b 0