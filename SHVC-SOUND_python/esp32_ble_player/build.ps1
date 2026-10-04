param([string]$Port, [string]$ArduinoCli, [string]$ConfigFile)
$ErrorActionPreference = 'Stop'
if (!$ArduinoCli) {
    $cliCommand = Get-Command arduino-cli -ErrorAction SilentlyContinue
    if ($cliCommand) { $ArduinoCli = $cliCommand.Source }
    else { $ArduinoCli = Join-Path $env:USERPROFILE 'esp\arduino-cli.exe' }
}
if (!(Test-Path -LiteralPath $ArduinoCli)) { throw 'Install arduino-cli or specify -ArduinoCli.' }
if (!$ConfigFile) {
    $localConfig = Join-Path (Split-Path $ArduinoCli) 'arduino-cli.yaml'
    if (Test-Path -LiteralPath $localConfig) { $ConfigFile = $localConfig }
}
$configArgs = @()
if ($ConfigFile) { $configArgs = @('--config-file', $ConfigFile) }
$buildRoot = Join-Path $env:TEMP 'shvc-esp32-ble-player'
$sketchDir = Join-Path $buildRoot 'esp32_ble_player'
$outputDir = Join-Path $buildRoot 'output'
New-Item -ItemType Directory -Path $sketchDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'esp32_ble_player.ino') -Destination $sketchDir -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\esp32_spc_uploader\spc_bus.h') -Destination $sketchDir -Force
foreach ($name in @('bank_data.h','synth.h','midi_parser.h')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\esp32_ble_midi\$name") -Destination $sketchDir -Force
}
$bootSong = Join-Path $PSScriptRoot '..\esp32_spc_standalone\spc_data.h'
if (Test-Path -LiteralPath $bootSong) { Copy-Item -LiteralPath $bootSong -Destination $sketchDir -Force }
elseif (Test-Path -LiteralPath (Join-Path $sketchDir 'spc_data.h')) { Remove-Item -LiteralPath (Join-Path $sketchDir 'spc_data.h') }
# 3 MB application / 896 KB persistent song storage. No OTA slot.
& $ArduinoCli @configArgs compile --fqbn esp32:esp32:esp32doit-devkit-v1 --build-property build.partitions=huge_app --output-dir $outputDir $sketchDir
if ($LASTEXITCODE -ne 0) { throw 'ESP32 compilation failed' }
if ($Port) {
    & $ArduinoCli @configArgs upload --fqbn esp32:esp32:esp32doit-devkit-v1 -p $Port --input-dir $outputDir $sketchDir
    if ($LASTEXITCODE -ne 0) { throw 'ESP32 upload failed' }
}
