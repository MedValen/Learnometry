@echo off
REM Learnometry - start the study app.
cd /d "%~dp0"

if not exist ".venv\" (
  echo First run - setting up. This takes a minute.
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip >nul
  python -m pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)

REM A missing key is a warning, not a blocker. Everything that reads your study
REM history - the mastery map, the heatmap, adaptive practice - runs with no
REM API calls at all. Only generating new material needs a key.
if not exist ".env" (
  echo.
  echo   No .env file - starting in offline mode.
  echo   Practice, the mastery map, and analytics all work.
  echo   Generating new questions will not, until you add a key:
  echo     copy .env.example .env    then paste your key into it
  echo     https://console.anthropic.com/settings/keys
  echo.
)

echo.
echo   Learnometry is starting at http://127.0.0.1:8000
echo   Leave this window open. Press Ctrl+C here to stop.
echo.

start "" http://127.0.0.1:8000
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
