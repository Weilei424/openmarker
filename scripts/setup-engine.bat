@echo off
REM Set up the Python engine virtual environment on Windows.

set REPO_ROOT=%~dp0..
set ENGINE_DIR=%REPO_ROOT%\engine
set VENV_DIR=%ENGINE_DIR%\.venv

echo Setting up Python engine...

cd /d "%ENGINE_DIR%"

if not exist "%VENV_DIR%" (
    python -m venv "%VENV_DIR%"
)

"%VENV_DIR%\Scripts\pip" install --upgrade pip
"%VENV_DIR%\Scripts\pip" install -r requirements.txt

echo Engine setup complete.
echo To run: %VENV_DIR%\Scripts\python api\main.py
pause
