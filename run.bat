@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo       LocoEngine AI Gateway Server
echo ==========================================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in the PATH.
    echo Please install Python 3.10+ and try again.
    pause
    exit /b 1
)

:: Virtual environment path
set VENV_PATH=%~dp0.venv

if not exist "%VENV_PATH%" (
    echo [INFO] Creating Python virtual environment in %VENV_PATH%...
    python -m venv "%VENV_PATH%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo [INFO] Activating virtual environment...
call "%VENV_PATH%\Scripts\activate.bat"

echo [INFO] Ensuring latest pip...
python -m pip install --upgrade pip

echo [INFO] Installing/Checking requirements...
pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Setup complete. Starting LocoEngine Gateway...
echo.
python -m loco.main

pause
