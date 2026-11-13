@echo off
setlocal
cd /d "%~dp0"
set "LIFTOFF_PYTHONW="

if exist ".venv\Scripts\python.exe" if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\python.exe" -B -c "import PySide6, numpy, PIL" >nul 2>nul
  if not errorlevel 1 set "LIFTOFF_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
)

if not defined LIFTOFF_PYTHONW goto :missing_environment
start "LIFTOFF" "%LIFTOFF_PYTHONW%" -B "%~dp0launch_LIFTOFF.py"
exit /b 0

:missing_environment
echo No working LIFTOFF Python environment was found.
echo Run install_packages.bat in this folder, then launch again.
pause
exit /b 1
