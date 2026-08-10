@echo off
title Push coldreach to GitHub
cd /d "%~dp0"

echo.
echo   This uploads the CODE to GitHub.
echo   Your contacts, drafts, LinkedIn export, and API keys are ignored and stay
echo   on this computer. Nothing about the people in your list gets uploaded.
echo.
echo   First: go to https://github.com/new and create an EMPTY repository.
echo   Don't tick "Add a README". Then copy its URL and paste it below.
echo.
set /p REPO=  Repository URL (https://github.com/you/coldreach.git):

if "%REPO%"=="" (
  echo   No URL given. Nothing done.
  pause
  exit /b 1
)

git remote remove origin >nul 2>&1
git remote add origin %REPO%
if errorlevel 1 (
  echo   Couldn't set the remote. Check the URL.
  pause
  exit /b 1
)

echo.
echo   Pushing... a browser window may open to sign you into GitHub.
git push -u origin main
if errorlevel 1 (
  echo.
  echo   Push failed. The usual causes: the repo isn't empty, or the URL is wrong.
  pause
  exit /b 1
)

echo.
echo   Done. Your code is at %REPO%
echo.
pause
