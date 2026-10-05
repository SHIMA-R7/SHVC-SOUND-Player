param([string]$Port,[string]$WifiCredentials)
$ErrorActionPreference='Stop'
$cli=Join-Path $env:USERPROFILE 'esp/arduino-cli.exe'
$root=Join-Path $env:TEMP 'shvc-apu-bridge'
$sketch=Join-Path $root 'esp32_apu_bridge'
New-Item -ItemType Directory -Force $sketch | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'esp32_apu_bridge.ino') -Destination $sketch -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ble_transport.h') -Destination $sketch -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'wifi_transport.h') -Destination $sketch -Force
if($WifiCredentials) {
 Copy-Item -LiteralPath $WifiCredentials -Destination (Join-Path $sketch 'wifi_credentials.h') -Force
} else {
 @('#define SHVC_WIFI_SSID ""','#define SHVC_WIFI_PASSWORD ""') | Set-Content -Path (Join-Path $sketch 'wifi_credentials.h') -Encoding ascii
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../esp32_spc_uploader/spc_bus.h') -Destination $sketch -Force
& $cli --config-file (Join-Path $env:USERPROFILE 'esp/arduino-cli.yaml') compile --fqbn esp32:esp32:esp32doit-devkit-v1 --build-property build.partitions=huge_app --build-property upload.maximum_size=3145728 --output-dir (Join-Path $root 'output') $sketch
if($LASTEXITCODE -ne 0) { throw 'Bridge build failed.' }
if($Port) {
 & $cli --config-file (Join-Path $env:USERPROFILE 'esp/arduino-cli.yaml') upload --fqbn esp32:esp32:esp32doit-devkit-v1 -p $Port --input-dir (Join-Path $root 'output') $sketch
 if($LASTEXITCODE -ne 0) { throw 'Bridge upload failed.' }
}
