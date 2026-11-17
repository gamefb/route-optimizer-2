@echo off
cd /d "%~dp0"
echo Building and starting Route Planner. This takes a few minutes...
docker compose up -d --build > docker-start.log 2>&1
docker compose ps >> docker-start.log 2>&1
timeout /t 8 /nobreak > nul
docker compose logs --tail 60 api >> docker-start.log 2>&1
echo Done. You can close this window.
pause
