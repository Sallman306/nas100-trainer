@echo off
REM Start the NAS100 Trade Trainer and open it in the browser.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
REM Open the browser after a short delay so the server is up first.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"
python -m uvicorn server:app
pause
