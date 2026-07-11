@echo off
setlocal
cd /d "%~dp0"
set "PROJECT_DIR=%CD%"
".venv\Scripts\firefly.exe" desktop --cwd "%PROJECT_DIR%"
if errorlevel 1 (
  echo.
  echo Firefly exited with code %errorlevel%.
  pause
)
