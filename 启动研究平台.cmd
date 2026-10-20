@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp004_建模\交互验证平台\start.ps1"
if errorlevel 1 pause
