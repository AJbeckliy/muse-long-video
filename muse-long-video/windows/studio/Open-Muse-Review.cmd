@echo off
setlocal
if exist "%~dp0..\runtime\python.exe" (
  "%~dp0..\runtime\python.exe" -B "%~dp0launch.py"
) else (
  python -B "%~dp0launch.py"
)
if errorlevel 1 pause
