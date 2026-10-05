param([string]$Port='COM6')
$ErrorActionPreference='Stop'
$cli=Join-Path $env:USERPROFILE 'esp/arduino-cli.exe'
$built=Join-Path $env:TEMP 'shvc-esp32-ble-player/output'
$sketch=Join-Path $env:TEMP 'shvc-esp32-ble-player/esp32_ble_player'
if(!(Test-Path -LiteralPath (Join-Path $built 'esp32_ble_player.ino.bin'))) { throw 'Previously built BLE firmware is missing; rebuild esp32_ble_player first.' }
& $cli --config-file (Join-Path $env:USERPROFILE 'esp/arduino-cli.yaml') upload --fqbn esp32:esp32:esp32doit-devkit-v1 -p $Port --input-dir $built $sketch
if($LASTEXITCODE -ne 0) { throw 'BLE firmware restore failed.' }
