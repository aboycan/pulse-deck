@echo off
REM PulseDeck one-step setup for Windows. If Smart App Control blocks this file, double-click install.py instead.
REM INTERNET CONNECTION REQUIRED: downloads Python (if missing), Python packages and the libmpv audio engine.
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo.
echo  PulseDeck setup
echo  NOTE: An internet connection is required for this first-time setup.
echo.

set "PY="
REM Prefer the Python launcher, then python on PATH; require 3.11 or newer.
for %%C in ("py -3.13" "py -3.12" "py -3.11" "python") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=%%~C"
    )
)
REM PY holds either a launcher command (py -3.12) or a quoted full path.
REM Check the default per-user install location (covers a fresh install in this session).
if not defined PY (
    for %%V in (313 312 311) do (
        if not defined PY if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" set PY="%LocalAppData%\Programs\Python\Python%%V\python.exe"
    )
)

if not defined PY (
    echo Python 3.11+ was not found.
    where winget >nul 2>nul
    if errorlevel 1 (
        echo Please install Python 3.12 from https://www.python.org/downloads/ ^(tick "Add Python to PATH"^),
        echo then run install.bat again.
        pause
        exit /b 1
    )
    choice /m "Download and install Python 3.12 now with winget (internet required)"
    if errorlevel 2 exit /b 1
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
        set PY="%LocalAppData%\Programs\Python\Python312\python.exe"
    ) else (
        echo Python was installed, but this window cannot see it yet. Close this window and run install.bat again.
        pause
        exit /b 1
    )
)

echo Using Python: !PY!
!PY! scripts\setup_dev.py %*
if errorlevel 1 (
    echo.
    echo Setup did not finish. Read the messages above, fix the problem and run install.bat again.
    pause
    exit /b 1
)
echo.
echo Done. Double-click run.bat to start PulseDeck.
pause
