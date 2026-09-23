@echo off
rem Downloads the latest Paddock Legacy from GitHub and installs it over this folder.
rem Your careers, logins and backups live in %LOCALAPPDATA%\F1UniverseTracker and are never touched.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" & pause & exit /b
