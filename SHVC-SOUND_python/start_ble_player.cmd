@echo off
setlocal
set "BLE_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BLE_PYTHON%" (
    "%BLE_PYTHON%" "%~dp0tools\ble_player_gui.py"
) else (
    py -3 "%~dp0tools\ble_player_gui.py"
)
if errorlevel 1 pause
