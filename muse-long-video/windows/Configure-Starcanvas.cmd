@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pair.ps1"
if errorlevel 1 exit /b 1
call Restart-Studio.cmd
if errorlevel 1 pause
