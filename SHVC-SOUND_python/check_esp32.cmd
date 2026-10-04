@echo off
cd /d "%~dp0"
"C:\Users\Yugo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" tools\esp32_check.py %*
pause
