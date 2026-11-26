@echo off
cd /d "%~dp0"
set "N3PY=py -3.12"
where py >nul 2>nul || set "N3PY=python"

rem Prefer the pywebview UI; fall back to the classic Tk app.
%N3PY% -c "import webview" >nul 2>nul
if errorlevel 1 goto classic
if not exist "app\web\index.html" goto classic

%N3PY% app\webapp.py
if not errorlevel 1 goto done
echo Web UI failed, falling back to the classic app...
:classic
%N3PY% app\main.py
:done
if errorlevel 1 pause
