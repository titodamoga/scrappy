@echo off
setlocal EnableExtensions
title Scrappy
cd /d "%~dp0"
set "SCRAPPY_VENDOR="

if not exist "%~dp0python\python.exe" (
    echo.
    echo ERROR: falta python\python.exe, el interprete incluido con Scrappy.
    echo Restaura la carpeta python completa desde una copia de Scrappy.
    echo No se usa ni se modifica el Python instalado en el PC.
    echo.
    pause
    exit /b 1
)

echo Ejecutando Scrappy con el Python integrado ...
echo.
"%~dp0python\python.exe" "%~dp0scrappy.py"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
    echo Scrappy termino con errores ^(codigo %RESULT%^). Revisa el mensaje anterior.
) else (
    echo Scrappy ha terminado. Los resultados estan en la carpeta ENTREGA.
)
echo.
pause
exit /b %RESULT%
