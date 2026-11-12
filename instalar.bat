@echo off
rem Instalacion (una sola vez): crea el entorno de Python e instala las librerias.
chcp 65001 > nul
cd /d "%~dp0"
title Instalacion - Estimacion de biocombustibles
set PY=
where py > nul 2> nul && set PY=py -3
if not defined PY (where python > nul 2> nul && set PY=python)
if not defined PY (
    echo No se encontro Python. Instalarlo desde https://www.python.org/downloads/
    echo marcando la opcion "Add python.exe to PATH", y volver a correr este archivo.
    goto :error
)
echo Creando el entorno de Python en .venv ...
%PY% -m venv .venv || goto :error
echo Instalando las librerias (tarda unos minutos) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip > nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
echo.
echo Listo. Para estimar el mes, doble clic en correr_estimacion.bat
pause
exit /b 0

:error
echo.
echo La instalacion no se completo. Revisar el mensaje de arriba (README, seccion "Si algo falla").
pause
exit /b 1
