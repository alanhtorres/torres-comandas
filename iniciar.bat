@echo off
rem Inicia o servidor do Torres Comandas. Deixe esta janela aberta.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Rode primeiro o instalar.bat
  pause
  exit /b 1
)
title Torres Comandas - servidor (nao feche esta janela)
.venv\Scripts\python main.py
pause
