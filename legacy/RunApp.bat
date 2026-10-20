@echo off
echo Starting PotteryApp...
set "PYTHONPATH=%~dp0..\core;%PYTHONPATH%"
cd /d "%~dp0"
py "%~dp0main.py"
pause
