@echo off
title Pottery Studio - Beta (Amit Test)
echo Starting Pottery Studio Beta...
py "%~dp0pottery_studio_beta.py" %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%
    pause
)
