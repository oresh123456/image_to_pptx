@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  One-click build: PyInstaller -> inject config -> Inno Setup
REM ============================================================

cd /d "%~dp0\.."

REM --- Read version from pyproject.toml ---
for /f "tokens=2 delims== " %%v in ('findstr /r "^version" pyproject.toml') do (
    set "VERSION=%%~v"
)
if not defined VERSION set "VERSION=0.1.0"
echo Version: %VERSION%

REM --- Check API keys in env ---
if not defined GEMINI_API_KEY (
    echo WARNING: GEMINI_API_KEY not set. Config will have placeholder.
    set "GEMINI_API_KEY=__GEMINI_API_KEY__"
)
if not defined REPLICATE_API_TOKEN (
    echo WARNING: REPLICATE_API_TOKEN not set. Config will have placeholder.
    set "REPLICATE_API_TOKEN=__REPLICATE_API_TOKEN__"
)

REM --- Generate config.toml from template ---
echo Generating config.toml...
powershell -Command "(Get-Content 'installer\config.toml.template') -replace '__GEMINI_API_KEY__', '%GEMINI_API_KEY%' -replace '__REPLICATE_API_TOKEN__', '%REPLICATE_API_TOKEN%' | Set-Content 'installer\config.toml'" || goto :error

REM --- Run PyInstaller ---
echo Running PyInstaller...
pyinstaller installer\slide_text_replacer.spec --distpath installer\dist --workpath installer\build -y || goto :error

REM --- Copy config.toml into dist ---
echo Copying config.toml to dist...
copy /y installer\config.toml installer\dist\slide_text_replacer\config.toml || goto :error

REM --- Run Inno Setup ---
echo Running Inno Setup...
where iscc >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: iscc not found. Install Inno Setup and add to PATH.
    goto :error
)
iscc /DAppVersion=%VERSION% installer\setup.iss || goto :error

echo.
echo ============================================================
echo  BUILD COMPLETE
echo  Installer: installer\output\Setup_SlideTextReplacer_v%VERSION%.exe
echo ============================================================
goto :eof

:error
echo BUILD FAILED
exit /b 1
