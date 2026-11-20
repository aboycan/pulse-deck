@echo off
REM Start PulseDeck. If Windows Smart App Control blocks this file, double-click PulseDeck.pyw instead.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo PulseDeck is not set up yet. Running install.bat first...
    call install.bat
    if errorlevel 1 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m pulsedeck.main %*
