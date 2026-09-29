@echo off
title Profile Test - Automatic Pottery Profile Analysis
echo Starting Profile Test App...
py profile_test.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%
    pause
)
