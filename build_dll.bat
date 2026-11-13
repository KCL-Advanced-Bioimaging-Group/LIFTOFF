@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\build.py --native-only %*
exit /b %errorlevel%
