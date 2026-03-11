@echo off
setlocal

REM Set up the Python engine virtual environment on Windows.
REM Python 3.11 is used as the stable baseline. 3.10+ also works with pyclipper 1.4.0.

set "REPO_ROOT=%~dp0.."
set "ENGINE_DIR=%REPO_ROOT%\engine"
set "VENV_DIR=%ENGINE_DIR%\.venv"

echo Setting up Python engine...

cd /d "%ENGINE_DIR%" || exit /b 1

REM Verify Python 3.11 exists
py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 is required but was not found.
    echo Please install Python 3.11 from https://www.python.org/downloads/
    exit /b 1
)

REM Create venv if needed
if not exist "%VENV_DIR%\Scripts\python.exe" (
    py -3.11 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        exit /b 1
    )
)

REM Upgrade pip
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: pip upgrade failed.
    exit /b 1
)

REM Install dependencies
"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency install failed. See output above.
    exit /b 1
)

echo Engine setup complete.
echo To run: "%VENV_DIR%\Scripts\python.exe" api\main.py
pause
