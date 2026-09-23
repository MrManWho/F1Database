@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || exit /b 1
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
)
".venv\Scripts\python.exe" -m pip install pyinstaller || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --name "F1 Universe Tracker" ^
  --add-data "templates;templates" --add-data "static;static" launcher.py || exit /b 1
echo.
echo Built dist\F1 Universe Tracker.exe - career saves stay in %%LOCALAPPDATA%%\F1UniverseTracker
pause
