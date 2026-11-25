@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0.."
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -X utf8 windows\start-native.py
) else (
    python -X utf8 windows\start-native.py
)
pause
