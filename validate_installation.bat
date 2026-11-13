@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto :missing_environment
".venv\Scripts\python.exe" -B validate_installation.py
if errorlevel 1 (
  echo.
  echo Validation failed. Review the error above.
  pause
  exit /b 1
)

echo.
pause
exit /b 0

:missing_environment
echo No LIFTOFF environment was found. Run install_packages.bat first.
pause
exit /b 1
