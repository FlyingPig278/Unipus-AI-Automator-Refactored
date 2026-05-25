@echo off
setlocal enabledelayedexpansion

REM #################################################################################
REM #                    Unipus AI Automator - Packaging Script                     #
REM #  This script automates the creation of "Lite", "Portable", and "Update"       #
REM #  packages for the application. It uses git-archive and git-diff to ensure     #
REM #  a clean source tree and PowerShell for reliable zip compression.            #
REM #################################################################################

REM --- Configuration ---
set "PROJECT_NAME=Unipus-AI-Automator"
set "LITE_STAGING_DIR=__temp_lite_build"
set "PORTABLE_STAGING_DIR=__temp_portable_build"
set "UPDATE_STAGING_DIR=__temp_update_build"
set "SOURCE_ARCHIVE=source.zip"
set "SOURCE_DIFF=diff.patch"

REM --- Get Version from User ---
set "VERSION="
set /p "VERSION=Please enter the version number to package (e.g., 1.2.0): "
if not defined VERSION (
    echo.
    echo [ERROR] Version number not provided, script will exit.
    pause
    exit /b 1
)
echo.
echo ==========================================================
echo           Starting package %PROJECT_NAME% v%VERSION%
echo ==========================================================
echo.

REM --- Pre-run Checks ---
echo [INFO] Checking required files...
if not exist "run.bat" (
    echo [ERROR] 'run.bat' not found. Please ensure this script is in the same directory as 'run.bat'.
    pause
    exit /b 1
)
if not exist "run-portable.bat" (
    echo [ERROR] 'run-portable.bat' not found. Cannot package Portable version.
    pause
    exit /b 1
)
if not exist "python-embed" (
    echo [ERROR] 'python-embed' directory not found. Cannot package Portable version.
    pause
    exit /b 1
)

REM --- Check Git and PowerShell availability ---
echo [INFO] Checking Git...
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is not installed or not in PATH.
    pause
    exit /b 1
)

git status --porcelain 2>nul | findstr . >nul
if not errorlevel 1 (
    echo [ERROR] Working tree has uncommitted or untracked changes.
    echo         package.bat uses "git archive HEAD", so dirty files would be missing from the package.
    echo         Commit or stash your changes before packaging.
    pause
    exit /b 1
)

echo [INFO] Checking PowerShell...
powershell -Command "exit 0" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PowerShell is not available.
    pause
    exit /b 1
)

REM --- Get Previous Tag ---
set "PREVIOUS_TAG="
set "TAG_AVAILABLE=0"

REM Check if any tags exist
git tag 2>nul | findstr . >nul && set "TAG_AVAILABLE=1"

if !TAG_AVAILABLE!==1 (
    REM Get the latest tag
    for /f "delims=" %%i in ('git describe --tags --abbrev=0') do set "PREVIOUS_TAG=%%i"

    REM Fallback if git describe fails
    if "%PREVIOUS_TAG%"=="" (
        for /f "delims=" %%i in ('git tag --sort=-v:refname') do (
            if not defined PREVIOUS_TAG set "PREVIOUS_TAG=%%i"
        )
    )
) else (
    echo [INFO] No Git tags found in repository.
    set "PREVIOUS_TAG=initial"
)

REM Check if we got a tag
if "%PREVIOUS_TAG%"=="" (
    echo [ERROR] Could not retrieve Git tag. Using 'initial' as default.
    set "PREVIOUS_TAG=initial"
)

if "%PREVIOUS_TAG%"=="initial" (
    echo [INFO] This is the first release. Using default tag: %PREVIOUS_TAG%
) else (
    echo [INFO] Previous Git tag: %PREVIOUS_TAG%
)

REM --- Cleanup from previous runs ---
if exist "%LITE_STAGING_DIR%" rmdir /s /q "%LITE_STAGING_DIR%"
if exist "%PORTABLE_STAGING_DIR%" rmdir /s /q "%PORTABLE_STAGING_DIR%"
if exist "%UPDATE_STAGING_DIR%" rmdir /s /q "%UPDATE_STAGING_DIR%"

REM =================================================================
REM # 1. LITE VERSION
REM =================================================================
echo.
echo [1/3] --- Creating Lite version ---

REM 1.1. Create staging directory and archive source
echo      - Creating temporary directory and exporting source code...
mkdir "%LITE_STAGING_DIR%"
git archive HEAD --format=zip --output="%LITE_STAGING_DIR%\%SOURCE_ARCHIVE%" > nul
if %errorlevel% neq 0 (
    echo [ERROR] 'git archive' command failed. Ensure you are running this script in a git repository.
    goto cleanup
)

REM 1.2. Unpack source and copy assets
echo      - Extracting source code and copying run.bat...
powershell -Command "Expand-Archive -Path '%LITE_STAGING_DIR%\%SOURCE_ARCHIVE%' -DestinationPath '%LITE_STAGING_DIR%'"
del "%LITE_STAGING_DIR%\%SOURCE_ARCHIVE%"

REM Check if files were extracted
echo [INFO] Files in '%LITE_STAGING_DIR%':
dir "%LITE_STAGING_DIR%"

copy "run.bat" "%LITE_STAGING_DIR%\" > nul

REM 1.3. Create final zip file
set "LITE_ZIP_NAME=%PROJECT_NAME%-Lite-v%VERSION%.zip"
if exist "%LITE_ZIP_NAME%" del "%LITE_ZIP_NAME%"
echo      - Compressing to %LITE_ZIP_NAME...

REM Ensure correct directory and path handling
powershell -NoProfile -Command "Compress-Archive -Path '%LITE_STAGING_DIR%\*' -DestinationPath '%CD%\%LITE_ZIP_NAME%'"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create Lite version zip package.
    goto cleanup
)
echo      - Lite version created successfully!

REM =================================================================
REM # 2. PORTABLE VERSION
REM =================================================================
echo.
echo [2/3] --- Creating Portable version ---

REM 2.1. Create staging directory and archive source
echo      - Creating temporary directory and exporting source code...
mkdir "%PORTABLE_STAGING_DIR%"
git archive HEAD --format=zip --output="%PORTABLE_STAGING_DIR%\%SOURCE_ARCHIVE%" > nul
if %errorlevel% neq 0 (
    echo [ERROR] 'git archive' command failed.
    goto cleanup
)

REM 2.2. Unpack source
echo      - Extracting source code...
powershell -Command "Expand-Archive -Path '%PORTABLE_STAGING_DIR%\%SOURCE_ARCHIVE%' -DestinationPath '%PORTABLE_STAGING_DIR%'"

REM Check if files were extracted
echo [INFO] Files in '%PORTABLE_STAGING_DIR%':
dir "%PORTABLE_STAGING_DIR%"

del "%PORTABLE_STAGING_DIR%\%SOURCE_ARCHIVE%"

REM 2.3. Copy portable assets
echo      - Copying 'python-embed' directory (this may take some time)...
xcopy "python-embed" "%PORTABLE_STAGING_DIR%\python-embed\" /s /e /i /q /y
echo      - Copying and renaming 'run-portable.bat' to 'run.bat'...
copy "run-portable.bat" "%PORTABLE_STAGING_DIR%\run.bat" > nul

REM 2.4. Create final zip file
set "PORTABLE_ZIP_NAME=%PROJECT_NAME%-Portable-v%VERSION%.zip"
if exist "%PORTABLE_ZIP_NAME%" del "%PORTABLE_ZIP_NAME%"
echo      - Compressing to %PORTABLE_ZIP_NAME% (this may take longer)...

REM Ensure correct directory and path handling
powershell -NoProfile -Command "Compress-Archive -Path '%PORTABLE_STAGING_DIR%\*' -DestinationPath '%CD%\%PORTABLE_ZIP_NAME%'"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create Portable version zip package.
    goto cleanup
)
echo      - Portable version created successfully!

REM =================================================================
REM # 3. UPDATE VERSION (From previous Git tag to current version)
REM =================================================================
echo.
echo [3/3] --- Creating Update version ---

if "%PREVIOUS_TAG%"=="initial" (
   echo      - This is the first version, skipping update package creation.
) else (
   echo      - Creating update package from %PREVIOUS_TAG% to v%VERSION%...

   REM 3.1. Create staging directory
   mkdir "%UPDATE_STAGING_DIR%" 2>nul

   REM 3.2. Get and copy CHANGED/ADDED files.
   echo      - Collecting and copying new and modified files...
   set "ADDED_MODIFIED_COUNT=0"
   for /f "delims=" %%f in ('git diff --name-only --diff-filter=dACM %PREVIOUS_TAG%..HEAD') do (
       set "gitpath=%%f"

       REM ** FIX: Convert forward slashes from git path to backslashes for Windows commands **
       set "winpath=!gitpath:/=\!"

       REM Create the directory structure for the file (PowerShell handles both / and \)
       powershell -Command "New-Item -ItemType Directory -Force -Path (Split-Path -Path '%UPDATE_STAGING_DIR%\!gitpath!' -Parent)" > nul

       REM Copy the file using the corrected Windows-compatible path
       copy "!winpath!" "%UPDATE_STAGING_DIR%\!winpath!" > nul

       set /a ADDED_MODIFIED_COUNT+=1
   )
   echo      - Found !ADDED_MODIFIED_COUNT! new/modified files.

   REM 3.3. Get DELETED files and create a list.
   echo      - Collecting deleted file information...
   set "DELETED_COUNT=0"
   (for /f "delims=" %%f in ('git diff --name-only --diff-filter=D %PREVIOUS_TAG%..HEAD') do (
       echo %%f
       set /a DELETED_COUNT+=1
   )) > "%UPDATE_STAGING_DIR%\files_to_delete.txt"

   REM If the file is empty because there were no deletions, delete it.
   if !DELETED_COUNT!==0 (
       del "%UPDATE_STAGING_DIR%\files_to_delete.txt"
       echo      - Found no deleted files.
   ) else (
       echo      - Found !DELETED_COUNT! deleted files. List saved to files_to_delete.txt.
   )

   REM 3.4. Check if there are any changes at all.
   set /a "TOTAL_CHANGES = ADDED_MODIFIED_COUNT + DELETED_COUNT"
   if !TOTAL_CHANGES!==0 (
       echo      - No files changed, added, or deleted. Skipping update package creation.
   ) else (
       echo      - Total changes: !TOTAL_CHANGES! files. Proceeding with packaging.

       REM 3.5. Create improved update README
       (
           echo Unipus AI Automator - Update Instructions
           echo =========================================
           echo.
           echo Update from version: %PREVIOUS_TAG%
           echo Update to version:   v%VERSION%
           echo.
           echo HOW TO UPDATE:
           echo ----------------
           echo 1. IMPORTANT: Back up your existing installation directory first.
           echo 2. If 'files_to_delete.txt' exists in this package, open it and DELETE all listed files and folders from your installation directory.
           echo 3. Copy all other files and folders from this package into your installation directory, overwriting any existing files.
           echo.
       ) > "%UPDATE_STAGING_DIR%\UPDATE_README.txt"

       REM 3.6. Create a simple changelog
       git log %PREVIOUS_TAG%..HEAD --oneline --no-merges > "%UPDATE_STAGING_DIR%\CHANGELOG.txt"

       REM 3.7. Create final update zip package
       set "UPDATE_ZIP_NAME=%PROJECT_NAME%-update_%PREVIOUS_TAG%_to_v%VERSION%.zip"
       if exist "!UPDATE_ZIP_NAME!" del "!UPDATE_ZIP_NAME!"
       echo      - Compressing to !UPDATE_ZIP_NAME!...

       powershell -NoProfile -Command "Compress-Archive -Path '%UPDATE_STAGING_DIR%\*' -DestinationPath '%CD%\!UPDATE_ZIP_NAME!'"
       if %errorlevel% neq 0 (
           echo [ERROR] Failed to create update package.
       ) else (
           echo      - Update version created successfully!
       )
   )
)

REM =================================================================
REM # 4. CLEANUP
REM =================================================================
:cleanup
echo.
echo --- Cleaning up temporary files ---
if exist "%LITE_STAGING_DIR%" rmdir /s /q "%LITE_STAGING_DIR%"
if exist "%PORTABLE_STAGING_DIR%" rmdir /s /q "%PORTABLE_STAGING_DIR%"
if exist "%UPDATE_STAGING_DIR%" rmdir /s /q "%UPDATE_STAGING_DIR%"
echo      - Cleanup complete.

echo.
echo ==========================================================
echo           All packaging tasks are completed!
echo ==========================================================
echo.
pause
endlocal
