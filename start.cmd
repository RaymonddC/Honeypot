@echo off
setlocal
REM ============================================================================
REM  ITTU dev launcher (POC mode) — one click to (re)start the whole app.
REM  Opens infra (docker), then the backend and frontend each in its own window.
REM  Close those two windows (or Ctrl+C in each) to stop the app.
REM ============================================================================
set "ROOT=%~dp0"

echo.
echo === ITTU dev launcher ===
echo.

echo [1/3] Starting Postgres + Redis (docker-compose up -d)...
docker-compose up -d
if errorlevel 1 (
  echo     WARNING: docker-compose failed - is Docker Desktop running?
  echo     POC mode runs fine without it, so continuing anyway.
)

echo [2/3] Backend  -^> new window  (http://localhost:8000)
start "ITTU backend" /d "%ROOT%backend" cmd /k "call .venv\Scripts\activate.bat && uvicorn app.main:app --reload"

echo [3/3] Frontend -^> new window  (http://localhost:3000)
start "ITTU frontend" /d "%ROOT%frontend" cmd /k "npm run dev"

echo.
echo Two windows opened:
echo   Backend : http://localhost:8000/health   (wait for "Application startup complete")
echo   Frontend: http://localhost:3000
echo.
echo To STOP: close those two windows (or Ctrl+C in each).
echo To stop infra too:  docker-compose down
echo.
echo This launcher window can be closed now.
endlocal
