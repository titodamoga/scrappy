@echo off
setlocal
cd /d "%~dp0"
python -c "import sys,sysconfig,struct; sys.exit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,15) and struct.calcsize('P') == 8 and not sysconfig.get_config_var('Py_GIL_DISABLED') else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: la reparacion requiere CPython 3.15 x64 normal con pip instalado.
    echo Alternativa: restaura vendor desde una copia completa de Scrappy.
    pause
    exit /b 1
)
echo Instalando dependencias fijadas en vendor ...
python -m pip install --upgrade --target vendor ^
    pymupdf==1.28.2 ^
    Pillow==13.0.0 ^
    numpy==2.5.5 ^
    opencv-python-headless==5.0.0.93
if errorlevel 1 (
    echo.
    echo ERROR: no se pudieron instalar las dependencias.
    pause
    exit /b 1
)
echo.
echo Listo. Ya puedes ejecutar SCRAPPY.BAT.
pause
