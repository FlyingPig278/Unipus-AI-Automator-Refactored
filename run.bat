@echo off
setlocal enabledelayedexpansion
title Unipus AI Automator Lite

echo =================================================================
echo  Unipus AI Automator (Lite版)
echo =================================================================
echo.

REM --- 配置区域 ---
set "VENV_DIR=.venv"
set "PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"

REM 步骤1: 检查系统 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    cls
    echo =================================================================
    echo  [错误] 未检测到 Python 环境
    echo =================================================================
    echo.
    echo 您的电脑尚未安装 Python，无法运行 Lite 版。
    echo 请任选以下一种解决方案：
    echo.
    echo -----------------------------------------------------------------
    echo  方案 A [最推荐 - 省心]：
    echo  请去下载本软件的 "便携独立版 [Portable Edition]"。
    echo  该版本内置环境，无需安装任何东西，解压即用。
    echo -----------------------------------------------------------------
    echo.
    echo  方案 B [技术流 - 自行安装]：
    echo  访问 python.org 下载安装 Python。
    echo.
    echo  [版本避坑指南]:
    echo   √ 推荐: Python 3.13 [完美运行] 或 3.12
    echo   X 禁止: 不要安装 Python 3.14 [依赖库尚未适配]
    echo   ! 注意: 安装时务必勾选 "Add Python to PATH"
    echo -----------------------------------------------------------------
    echo.
    pause
    exit /b 1
)

REM 步骤2: 检查/创建虚拟环境
echo [1/4] 正在检查运行环境...
if not exist "%VENV_DIR%" (
    echo       首次运行，正在为您创建虚拟环境[.venv]...
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败。可能是权限不足。
        pause
        exit /b 1
    )
    echo       虚拟环境已建立。
) else (
    echo       检测到已有环境，准备启动。
)

REM 虚拟环境路径定义
set "VENV_PYTHON=.\%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=.\%VENV_DIR%\Scripts\pip.exe"

REM 步骤3: 依赖检查 (完全显示进度)
echo [2/4] 正在校验依赖库...
echo       [提示] 首次运行可能需要下载大型文件，请关注下方进度条...
echo.

REM 去掉了 >nul，让 pip 显示进度条
"%VENV_PIP%" install -r requirements.txt -i %PYPI_INDEX% --no-warn-script-location

if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败！请检查网络连接或报错信息。
    pause
    exit /b 1
)

REM 步骤4: 浏览器检查 (完全显示进度)
echo.
echo [3/4] 检查浏览器内核...
echo       [提示] 正在调用 Playwright 检查/下载浏览器...

"%VENV_PYTHON%" -m playwright install chromium

if %errorlevel% neq 0 (
    echo [警告] 浏览器下载出现问题，稍后程序可能会报错。
) else (
    echo [成功] 浏览器内核就绪。
)

set "ESPEAK_DATA_PATH=%~dp0.venv\Lib\site-packages\piper\espeak-ng-data"

echo.
echo =================================================================
echo  环境准备完毕，正在启动...
echo =================================================================
echo.

REM 步骤5: 启动主程序
set "PYTHONPATH=%~dp0"

"%VENV_PYTHON%" main.py

echo.
echo [信息] 程序已退出。
pause