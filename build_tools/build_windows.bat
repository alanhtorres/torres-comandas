@echo off
REM Atalho para rodar build_windows.ps1 sem precisar ajustar a politica de execucao do PowerShell.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
