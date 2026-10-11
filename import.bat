@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: import.bat "https://open.spotify.com/track/ID"
  exit /b 1
)
".venv\Scripts\python.exe" import_spotify.py %*
