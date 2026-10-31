@echo off
rem ============================================================
rem  Construye PDF2MIDI.exe (un solo fichero) en Windows 10/11
rem  Requisitos: Python 3.11 o 3.12 de 64 bits  (https://python.org)
rem              e internet SOLO para esta construccion.
rem ============================================================
setlocal
cd /d "%~dp0"

set PY=
py -3.12 --version >nul 2>nul && set PY=py -3.12
if "%PY%"=="" py -3.11 --version >nul 2>nul && set PY=py -3.11
if "%PY%"=="" python --version >nul 2>nul && set PY=python
if "%PY%"=="" (
  echo No encuentro Python. Instala Python 3.12 de 64 bits desde python.org y vuelve a ejecutar.
  pause & exit /b 1
)

%PY% -m venv .venv || (echo Error creando el entorno & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :err
pip install -r requirements.txt || goto :err
set PYTHONPATH=%CD%\src
python tools\fetch_models.py || goto :err
pyinstaller --noconfirm --clean pdf2midi.spec || goto :err

echo.
echo ============================================================
echo  Listo:  %CD%\dist\PDF2MIDI.exe
echo ============================================================
pause
exit /b 0

:err
echo.
echo Algo ha fallado. Revisa los mensajes de arriba.
pause
exit /b 1
