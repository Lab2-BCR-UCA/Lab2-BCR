@echo off
rem Estimacion mensual de biodiesel y bioetanol: doble clic.
rem Descarga los datos, estima el mes, lo registra y abre el informe.
chcp 65001 > nul
cd /d "%~dp0"
title Estimacion de biocombustibles
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo Falta instalar el entorno: doble clic en instalar.bat y despues volver a correr este archivo.
    goto :error
)
".venv\Scripts\python.exe" scripts\salida_mensual.py --abrir %*
rem 3: todavia no se puede estimar el mes (no es un error). Va antes de "errorlevel 1"
rem porque "if errorlevel N" es verdadero para cualquier codigo mayor o igual a N.
if errorlevel 3 goto :todavia
if errorlevel 1 goto :error
echo.
echo Listo. Los archivos del mes quedaron en la carpeta resultados.
pause
exit /b 0

:todavia
echo.
echo No se estimo el mes todavia. No es un error del programa: volver a correr cuando indica el mensaje de arriba.
pause
exit /b 0

:error
echo.
echo No se pudo completar. Revisar el mensaje de arriba (README, seccion "Si algo falla").
pause
exit /b 1
