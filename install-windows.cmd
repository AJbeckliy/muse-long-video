@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0muse-long-video\scripts\setup_windows.ps1"
if errorlevel 1 (
  echo.
  echo Setup incomplete. Read the error above. No video generation was submitted.
  pause
)
