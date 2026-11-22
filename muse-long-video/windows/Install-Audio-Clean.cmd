@echo off
setlocal
cd /d "%~dp0"
"%~dp0runtime\python.exe" -B "%~dp0audio-setup.py"
if errorlevel 1 (pause & exit /b 1)
call Restart-Studio.cmd
if errorlevel 1 pause
