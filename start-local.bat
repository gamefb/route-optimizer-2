@echo off
rem Run Route Planner on this computer, without Docker. See run_local.py for what it does.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 run_local.py %*
) else (
    python run_local.py %*
)
if errorlevel 1 pause
