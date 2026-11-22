@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0muse-long-video\install-skill.ps1" %*
exit /b %errorlevel%
