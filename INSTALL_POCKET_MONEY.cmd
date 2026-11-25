@echo off
title Install Pocket Money
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_shortcut.ps1"
echo.
pause
