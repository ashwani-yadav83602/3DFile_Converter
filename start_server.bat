@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Project virtual environment not found: venv\Scripts\python.exe
    echo Create it and install dependencies with:
    echo   py -m venv venv
    echo   venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"Backend\venv\Scripts\python.exe" "Backend\app\start.py"
