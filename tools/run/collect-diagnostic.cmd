@echo off
rem Read-only log export. Copy beside mkw.exe with diagnose.py; double-click after a game session.
rem No game process, update or setup is launched. MKW_DIAG_PYTHON / MKW_DIAG_NO_PAUSE support CI testing.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "DIAG_PYTHON=%~dp0setup\python\python.exe"
if defined MKW_DIAG_PYTHON set "DIAG_PYTHON=%MKW_DIAG_PYTHON%"
if not exist "%DIAG_PYTHON%" (
    echo Python du port introuvable dans setup\python\python.exe.
    echo Aucun fichier du jeu n'a ete modifie.
    goto failure
)
set "DIAG_LOG=%~dp0logs\mkw.log"
if not "%~1"=="" set "DIAG_LOG=%~f1"
if not exist "%DIAG_LOG%" (
    echo Journal introuvable. Quittez normalement une partie, puis relancez ce collecteur.
    echo Vous pouvez aussi glisser un fichier .log sur ce script.
    goto failure
)
:choose_output
set "DIAG_OUT=%~dp0diagnostics\rapport-%RANDOM%-%RANDOM%"
if exist "%DIAG_OUT%" goto choose_output
mkdir "%DIAG_OUT%"
if errorlevel 1 goto failure
"%DIAG_PYTHON%" "%~dp0diagnose.py" "%DIAG_LOG%" --out "%DIAG_OUT%\fluidite.txt"
if errorlevel 1 goto failure
"%DIAG_PYTHON%" "%~dp0diagnose.py" --check-game "%~dp0." > "%DIAG_OUT%\compatibilite.txt"
echo.
echo Rapport termine dans :
echo %DIAG_OUT%
echo Envoyez uniquement fluidite.txt et compatibilite.txt dans la conversation en cours.
echo Si le dump est ailleurs, le controle de structure peut etre incomplet.
if not defined MKW_DIAG_NO_PAUSE pause
exit /b 0
:failure
echo Consultez TEST-WINDOWS.md pour une mesure avec MKW_TRACE=perf.
if not defined MKW_DIAG_NO_PAUSE pause
exit /b 1
