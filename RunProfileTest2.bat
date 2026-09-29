@echo off
title Profile Test 2 - Interactive Lasso Handle & Large View
echo Starting Profile Test 2 App...
py profile_test2.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%
    pause
)
