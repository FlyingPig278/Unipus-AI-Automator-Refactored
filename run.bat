@echo off
setlocal enabledelayedexpansion
title Unipus AI Automator Lite

chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo =================================================================
echo  Unipus AI Automator (Lite)
echo =================================================================
echo.

set "VENV_DIR=.venv"
set "PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PYTHONPATH=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.playwright-browsers"

python --version >nul 2>&1
if errorlevel 1 (
    cls
    echo =================================================================
    echo  [ERROR] Python was not found.
    echo =================================================================
    echo.
    echo  Please install Python 3.12 or 3.13 and make sure "Add Python to PATH"
    echo  was enabled, or use the Portable package instead.
    echo.
    pause
    exit /b 1
)

echo [1/3] Checking virtual environment...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo       Creating virtual environment: %VENV_DIR%
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo       Existing virtual environment found.
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

echo.
echo [2/3] Installing/updating Python dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip -i %PYPI_INDEX% --no-warn-script-location
"%VENV_PIP%" install -r requirements.txt -i %PYPI_INDEX% --upgrade --no-warn-script-location
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed. Check the network and messages above.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting application...
echo =================================================================
echo.
"%VENV_PYTHON%" main.py

echo.
echo [INFO] Program exited.
pause
