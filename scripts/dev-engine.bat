@echo off
REM Start the Python engine for local development.

set REPO_ROOT=%~dp0..
set ENGINE_DIR=%REPO_ROOT%\engine
set VENV_DIR=%ENGINE_DIR%\.venv

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Run scripts\setup-engine.bat first.
    pause
    exit /b 1
)

echo Starting OpenMarker engine on http://127.0.0.1:8765 ...
cd /d "%ENGINE_DIR%"
set PYTHONPATH=%ENGINE_DIR%
"%VENV_DIR%\Scripts\python" api/main.py
