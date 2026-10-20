@echo off
title Profile Test - Automatic Pottery Profile Analysis
echo Starting Profile Test App...
set "PYTHONPATH=%~dp0..\core;%PYTHONPATH%"
cd /d "%~dp0"
py "%~dp0profile_test.py" %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%
    pause
)
