@echo off
REM ===============================================================
REM slide_text_replacer - one-time setup
REM Finds a real Python install (not the Microsoft Store stub),
REM creates a fresh local venv, and installs the package and its deps.
REM ===============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo.
echo === slide_text_replacer: one-time setup ===
echo.

set PYEXE=

REM --- Try the py launcher first (most reliable when it exists) ---
where py >nul 2>nul
if !errorlevel! equ 0 (
    for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
        if exist "%%P" set PYEXE=%%P
    )
)

REM --- Fall back to python on PATH, but reject the MS Store stub ---
if "!PYEXE!"=="" (
    for /f "usebackq delims=" %%P in (`where python 2^>nul`) do (
        if "!PYEXE!"=="" (
            echo %%P | findstr /i "WindowsApps" >nul
            if !errorlevel! neq 0 (
                set PYEXE=%%P
            )
        )
    )
)

REM --- Last resort: probe common install paths directly ---
if "!PYEXE!"=="" (
    for %%V in (314 313 312 311 310) do (
        if "!PYEXE!"=="" (
            if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
                set PYEXE=%LocalAppData%\Programs\Python\Python%%V\python.exe
            )
        )
        if "!PYEXE!"=="" (
            if exist "C:\Python%%V\python.exe" (
                set PYEXE=C:\Python%%V\python.exe
            )
        )
        if "!PYEXE!"=="" (
            if exist "C:\Program Files\Python%%V\python.exe" (
                set PYEXE=C:\Program Files\Python%%V\python.exe
            )
        )
    )
)

if "!PYEXE!"=="" (
    echo [ERROR] Could not find a real Python installation.
    echo.
    echo Likely reason: Python is not installed, OR Windows is redirecting
    echo "python" to the Microsoft Store.
    echo.
    echo Fix:
    echo   1. Install Python 3.11+ from https://www.python.org/downloads/
    echo   2. During install, tick "Add python.exe to PATH".
    echo   3. Also turn OFF the Microsoft Store aliases:
    echo        Settings ^> Apps ^> Advanced app settings ^>
    echo        App execution aliases ^> disable python.exe and python3.exe
    echo   4. Re-run this setup.bat.
    echo.
    pause
    exit /b 1
)

echo Found Python: !PYEXE!
echo.

REM --- Verify Python 3.11+ (required for stdlib tomllib) ---
"!PYEXE!" -c "import sys; assert sys.version_info >= (3,11), sys.version" >nul 2>nul
if !errorlevel! neq 0 (
    echo [ERROR] Python at "!PYEXE!" is older than 3.11.
    echo         Install Python 3.11+ from python.org and re-run setup.bat.
    echo.
    pause
    exit /b 1
)

REM --- Validate any existing venv; recreate if stale ---
if exist venv (
    if exist venv\Scripts\python.exe (
        venv\Scripts\python.exe -c "import sys" >nul 2>nul
        if !errorlevel! neq 0 (
            echo Existing venv is broken ^(probably created on another PC^).
            echo Removing it and creating a fresh one...
            rmdir /s /q venv
        )
    ) else (
        echo Existing venv folder is incomplete. Removing it...
        rmdir /s /q venv
    )
)

REM --- Create venv if missing ---
if not exist venv (
    echo Creating virtual environment in .\venv ...
    "!PYEXE!" -m venv venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
) else (
    echo Reusing existing virtual environment.
)

REM --- Upgrade pip ---
echo.
echo Upgrading pip...
call venv\Scripts\python.exe -m pip install --upgrade pip --quiet

REM --- Install the package in editable mode (pulls all deps from pyproject.toml) ---
echo Installing slide_text_replacer and dependencies...
call venv\Scripts\python.exe -m pip install -e .
if !errorlevel! neq 0 (
    echo [ERROR] pip install failed. See messages above.
    pause
    exit /b 1
)

REM --- Remind user to create config.toml ---
if not exist config.toml (
    echo.
    echo IMPORTANT: Create config.toml with your API keys.
    echo See docs\config.md for the full template and instructions.
)

echo.
echo === Setup complete ===
echo.
echo Next steps:
echo   1. Create config.toml (see docs\config.md for template).
echo   2. Double-click scripts\run.bat to process a PPTX.
echo.
pause
