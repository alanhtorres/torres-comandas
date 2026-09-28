@echo off
rem Instala as dependencias do Torres Comandas (rodar uma vez so).
cd /d "%~dp0"

set PY=py -3
where py >nul 2>nul || set PY=python
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python nao encontrado.
  echo Instale pelo site python.org e marque a opcao "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

echo Criando ambiente...
%PY% -m venv .venv || goto erro
echo Instalando dependencias (precisa de internet so agora)...
.venv\Scripts\python -m pip install --upgrade pip || goto erro
.venv\Scripts\python -m pip install -r requirements.txt || goto erro

echo.
echo Instalacao concluida! Agora de dois cliques em iniciar.bat
echo.
pause
exit /b 0

:erro
echo.
echo Ocorreu um erro na instalacao. Veja a mensagem acima.
pause
exit /b 1
