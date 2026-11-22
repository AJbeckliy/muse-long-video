@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install-skill.ps1" %*
if errorlevel 1 (pause & exit /b 1)
