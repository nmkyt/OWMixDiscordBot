@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo The bot is not installed yet. Run first: python install.py
    pause
    exit /b 1
)
"venv\Scripts\python.exe" -m src.bot_controller
pause
