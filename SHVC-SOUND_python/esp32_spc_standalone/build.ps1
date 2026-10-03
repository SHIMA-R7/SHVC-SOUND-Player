param([string]$Port, [string]$ArduinoCli, [string]$ConfigFile)
$ErrorActionPreference = 'Stop'
if (!$ArduinoCli) {
    $cliCommand = Get-Command arduino-cli -ErrorAction SilentlyContinue
    if ($cliCommand) { $ArduinoCli = $cliCommand.Source }
    else { $ArduinoCli = Join-Path $env:USERPROFILE 'esp\arduino-cli.exe' }
}
if (!(Test-Path -LiteralPath $ArduinoCli)) { throw 'Install arduino-cli or specify -ArduinoCli.' }
if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'spc_data.h'))) { throw 'Run tools/prepare_standalone_spc.py with your SPC first.' }
if (!$ConfigFile) {
    $localConfig = Join-Path (Split-Path $ArduinoCli) 'arduino-cli.yaml'
    if (Test-Path -LiteralPath $localConfig) { $ConfigFile = $localConfig }
}
$configArgs = @()
if ($ConfigFile) { $configArgs = @('--config-file', $ConfigFile) }
$buildRoot = Join-Path $env:TEMP 'shvc-esp32-standalone'
$sketchDir = Join-Path $buildRoot 'esp32_spc_standalone'
$outputDir = Join-Path $buildRoot 'output'
New-Item -ItemType Directory -Path $sketchDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'esp32_spc_standalone.ino') -Destination $sketchDir -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'spc_data.h') -Destination $sketchDir -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\esp32_spc_uploader\spc_bus.h') -Destination $sketchDir -Force
& $ArduinoCli @configArgs compile --fqbn esp32:esp32:esp32doit-devkit-v1 --output-dir $outputDir $sketchDir
if ($LASTEXITCODE -ne 0) { throw 'ESP32 compilation failed' }
if ($Port) {
    & $ArduinoCli @configArgs upload --fqbn esp32:esp32:esp32doit-devkit-v1 -p $Port --input-dir $outputDir $sketchDir
    if ($LASTEXITCODE -ne 0) { throw 'ESP32 upload failed' }
}
