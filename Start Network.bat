@echo off
title coldreach network
cd /d "%~dp0"

set PY=python
where python >nul 2>&1 || set PY=py
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python isn't installed on this computer.
  echo   Get it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo.
  pause
  exit /b 1
)

%PY% -c "import requests, bs4, yaml" >nul 2>&1
if errorlevel 1 (
  echo   First run - installing the bits it needs. This takes a minute...
  %PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   Install failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
)

echo   Starting coldreach...
set COLDREACH_START=network
%PY% -m coldreach.server
if errorlevel 1 (
  echo.
  echo   Something went wrong. The error is above this line.
  pause
)
