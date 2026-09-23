@echo off
setlocal
cd /d "%~dp0"
title F1 Universe Tracker

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First launch: creating a private Python environment...
  py -3 -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" launcher.py %*
pause
exit /b 0

:fail
echo Setup failed. Check your internet connection and try again.
pause
exit /b 1
