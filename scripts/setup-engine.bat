@echo off
REM Set up the Python engine virtual environment on Windows.
REM Supported Python version: 3.11
REM pyclipper currently fails to build on Python 3.12+ (missing longintrepr.h).

set REPO_ROOT=%~dp0..
set ENGINE_DIR=%REPO_ROOT%\engine
set VENV_DIR=%ENGINE_DIR%\.venv

echo Setting up Python engine...

cd /d "%ENGINE_DIR%"

REM Check Python version before creating venv.
REM Extract major.minor and allow only Python 3.11.
for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set PY_VER=%%V
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
    set PY_MAJOR=%%A
    set PY_MINOR=%%B
)

if not "%PY_MAJOR%"=="3" (
    echo ERROR: Python 3.11 is required. Found: %PY_VER%
    echo Please install Python 3.11 from https://www.python.org/downloads/
    exit /b 1
)
if not "%PY_MINOR%"=="11" (
    echo ERROR: Python 3.11 is required. Found: %PY_VER%
    echo Python 3.12+ currently fails when building pyclipper (missing longintrepr.h).
    echo Please install Python 3.11 from https://www.python.org/downloads/
    exit /b 1
)

if not exist "%VENV_DIR%" (
    python -m venv "%VENV_DIR%"
)

REM Use the venv interpreter (not pip.exe) to avoid the "use python -m pip" warning.
"%VENV_DIR%\Scripts\python" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: pip upgrade failed.
    exit /b 1
)

"%VENV_DIR%\Scripts\python" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency install failed. See output above.
    exit /b 1
)

echo Engine setup complete.
echo To run: %VENV_DIR%\Scripts\python api\main.py
pause
