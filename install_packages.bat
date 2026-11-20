@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "INSTALL_TARGET=."
if /i "%~1"=="--dev" set "INSTALL_TARGET=.[dev]"
if not "%~1"=="" if /i not "%~1"=="--dev" goto :usage
if not "%~2"=="" goto :usage

pushd "%~dp0"
if errorlevel 1 (
  echo Could not open the LIFTOFF source folder.
  pause
  exit /b 1
)

set "VENV_PYTHON=.venv\Scripts\python.exe"
set "PYTHON_CHECK=import sys, sysconfig; sys.exit(not (sys.version_info[:2] == (3, 14) and sys.version_info.micro >= 10 and sys.version_info.releaselevel == 'final' and sys.implementation.name == 'cpython' and sysconfig.get_platform() == 'win-amd64' and not sysconfig.get_config_var('Py_GIL_DISABLED')))"
if exist "%VENV_PYTHON%" goto :check_environment

set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "PYLAUNCHER_ALLOW_INSTALL="
set "PYTHON_COMMAND=py.exe -3.14"
%PYTHON_COMMAND% -I -c "%PYTHON_CHECK%" >nul 2>&1
if not errorlevel 1 goto :create_environment
set "PYTHON_COMMAND=pymanager.exe exec -3.14"
%PYTHON_COMMAND% -I -c "%PYTHON_CHECK%" >nul 2>&1
if not errorlevel 1 goto :create_environment
set "PYTHON_COMMAND=python.exe"
%PYTHON_COMMAND% -I -c "%PYTHON_CHECK%" >nul 2>&1
if not errorlevel 1 goto :create_environment

echo LIFTOFF requires standard x64 CPython 3.14.10 or newer in the 3.14 series.
echo Get the Python Install Manager at https://www.python.org/downloads/windows/
echo Run "pymanager install --update 3.14", then run install_packages.bat again.
goto :failed

:create_environment
echo Creating the LIFTOFF environment in .venv...
%PYTHON_COMMAND% -I -m venv .venv
if errorlevel 1 (
  echo Could not create .venv. See the error above.
  goto :failed
)

:check_environment
"%VENV_PYTHON%" -I -c "%PYTHON_CHECK%"
if errorlevel 1 goto :incompatible_environment
if not exist ".venv\Scripts\pythonw.exe" goto :incompatible_environment

"%VENV_PYTHON%" -I -m pip --version >nul 2>&1
if errorlevel 1 (
  echo Setting up pip in .venv...
  "%VENV_PYTHON%" -I -m ensurepip --upgrade
  if errorlevel 1 (
    echo Could not set up pip in .venv. See the error above.
    goto :failed
  )
)

echo Installing LIFTOFF packages...
"%VENV_PYTHON%" -I -m pip install -e "%INSTALL_TARGET%"
if errorlevel 1 (
  echo Package installation failed. See the pip error above.
  goto :failed
)

echo Checking the installed runtime and native libraries...
"%VENV_PYTHON%" -I -B validate_installation.py
if errorlevel 1 (
  echo LIFTOFF validation failed. See the error above.
  goto :failed
)

echo.
echo Installation complete. You can now double-click launch_LIFTOFF.bat.
pause
popd
exit /b 0

:incompatible_environment
echo The existing .venv is incomplete or uses an incompatible version of Python.
echo Install standard x64 CPython 3.14.10 or newer in the 3.14 series.
echo Rename .venv to .venv-old, then run install_packages.bat again.

:failed
echo.
pause
popd
exit /b 1

:usage
echo Run install_packages.bat or install_packages.bat --dev.
pause
exit /b 1
