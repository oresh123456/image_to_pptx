@echo off
REM ===============================================================
REM slide_text_replacer - main launcher
REM Uses the venv's Python directly to avoid PATH / Store alias issues.
REM Run setup.bat once before using this.
REM ===============================================================

setlocal
cd /d "%~dp0.."

if not exist venv\Scripts\python.exe (
    echo [ERROR] Setup has not been run yet ^(or it failed^).
    echo         Double-click scripts\setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist config.toml (
    echo [ERROR] config.toml is missing.
    echo         Run scripts\setup.bat to create it, then paste your API keys.
    echo.
    pause
    exit /b 1
)

echo Starting slide_text_replacer...
echo (Two dialog boxes will open: one to select your .pptx, one to choose
echo  where to save the output.)
echo.

venv\Scripts\python.exe -m slide_text_replacer
set EXITCODE=%errorlevel%

echo.
if %EXITCODE% neq 0 (
    echo [!] Finished with errors. See messages above.
) else (
    echo [OK] Done.
)
echo.
pause
