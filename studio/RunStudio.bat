@echo off
title Pottery Studio
echo Starting Pottery Studio...
py "%~dp0pottery_studio.py" %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%
    pause
)
