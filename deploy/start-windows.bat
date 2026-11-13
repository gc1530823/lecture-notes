@echo off
chcp 65001 >nul
rem Lecture notes server (Windows). Double-click to run.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-windows.ps1" %*
pause
