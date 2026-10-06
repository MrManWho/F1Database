@echo off
rem Local development for Paddock Legacy 4.0 (see docs/LOCAL_DEV.md). Not used by Render or by run.bat.
rem   dev.bat                start the site on http://127.0.0.1:5050 with live reload (Ctrl+C stops it)
rem   dev.bat seed LOGIN     add the fictional 8-round test league
rem   dev.bat finale LOGIN   add the fictional league with only its last round left
rem   dev.bat where          show where local data lives
rem   dev.bat reset          set the local data aside and start empty next time
setlocal
cd /d "%~dp0"
title Paddock Legacy - LOCAL DEVELOPMENT

py -3.11 --version >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 is required. In PowerShell run:  winget install --id Python.Python.3.11 -e --source winget
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First start: creating a private Python 3.11 environment in .venv ...
  py -3.11 -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)"
if errorlevel 1 (
  echo The .venv folder was made with a different Python. Delete the .venv folder and run dev.bat again.
  pause
  exit /b 1
)

rem Install packages on first start, and again whenever requirements.txt changes.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt pytest || goto :fail
  copy /y requirements.txt ".venv\requirements.installed" >nul
)

".venv\Scripts\python.exe" dev.py %*
exit /b %errorlevel%

:fail
echo Setup failed. Check your internet connection and try again.
pause
exit /b 1
