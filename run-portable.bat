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
if not defined PLAYWRIGHT_DOWNLOAD_HOSTS set "PLAYWRIGHT_DOWNLOAD_HOSTS=https://npmmirror.com/mirrors/playwright,"
if not defined PLAYWRIGHT_DOWNLOAD_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
if not defined PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT set "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Embedded Python is missing: %PYTHON_EXE%
    echo        Please make sure the python-embed directory exists.
    pause
    exit /b 1
)

echo [1/2] Installing/updating Python dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt -i %PYPI_INDEX% --upgrade --no-warn-script-location
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed. Check the network and messages above.
    pause
    exit /b 1
)

echo.
echo [2/2] Starting application...
echo =================================================================
echo.
"%PYTHON_EXE%" main.py

echo.
echo [INFO] Program exited.
pause
