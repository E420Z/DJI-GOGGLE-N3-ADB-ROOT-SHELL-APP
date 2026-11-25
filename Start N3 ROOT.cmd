@echo off
cd /d "%~dp0"
py -3.12 app\main.py 2>nul || python app\main.py
if errorlevel 1 pause
