@echo off
echo Starting SDE 2 Backend in MOCK mode...

if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found.
    echo Please create it using: python -m venv .venv
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

python -m uvicorn app.main:app --host 127.0.0.1 --port 8001

pause