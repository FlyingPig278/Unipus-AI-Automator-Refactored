@echo off
setlocal enabledelayedexpansion
title Unipus AI Automator Portable

chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo =================================================================
echo  Unipus AI Automator (Portable)
echo =================================================================
echo.

set "PYTHON_DIR=%~dp0python-embed"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PYTHONPATH=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%PYTHON_DIR%\browsers"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Embedded Python is missing: %PYTHON_EXE%
    echo        Please make sure the python-embed directory exists.
    pause
    exit /b 1
)

echo [1/3] Installing/updating Python dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt -i %PYPI_INDEX% --upgrade --no-warn-script-location
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed. Check the network and messages above.
    pause
    exit /b 1
)

echo.
echo [2/3] Checking and repairing Playwright Chromium...
"%PYTHON_EXE%" scripts\repair_playwright.py
if errorlevel 1 (
    echo.
    echo [ERROR] Browser setup failed after automatic repair.
    echo        You can delete "%PLAYWRIGHT_BROWSERS_PATH%" and run this script again.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting application...
echo =================================================================
echo.
"%PYTHON_EXE%" main.py

echo.
echo [INFO] Program exited.
pause
