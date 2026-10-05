@echo off
cd /d "%~dp0"
"C:\Users\Yugo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" spc_gui.py
if errorlevel 1 pause
