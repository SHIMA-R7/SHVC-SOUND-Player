param([ValidateSet('BLE','SPP','WIFI')][string]$Transport='WIFI')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$python=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$out=Join-Path $root ('docs/tmp/'+$Transport.ToLower()+'-apu-relay.log')
$err=Join-Path $root ('docs/tmp/'+$Transport.ToLower()+'-apu-relay-error.log')
$env:PYTHONUTF8='1'
$relayScript=switch($Transport) { 'SPP' {'spp_relay.py'} 'WIFI' {'wifi_relay.py'} default {'ble_relay.py'} }
$relay=Start-Process $python -ArgumentList @('-u',('"'+(Join-Path $PSScriptRoot $relayScript)+'"')) -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
try {
  $deadline=[DateTime]::UtcNow.AddSeconds(45)
  do {
    if($relay.HasExited) { throw (Get-Content $err -Raw) }
    if([DateTime]::UtcNow -gt $deadline) { throw 'Bluetooth bridge connection timed out.' }
    Start-Sleep -Milliseconds 200
  } until ((Test-Path $out) -and (Select-String -Path $out -Pattern 'READY:' -Quiet))
  $env:SHVC_APU_PORT='BLE'
  $env:SHVC_APU_LOG=Join-Path $root ('docs/tmp/retroarch-'+$Transport.ToLower()+'-apu.log')
  $game=Start-Process (Join-Path $root 'docs/tmp/retroarch-portable/RetroArch-Win64/retroarch.exe') -ArgumentList @('--config',('"'+(Join-Path $PSScriptRoot 'shvc-retroarch.cfg')+'"'),'-L',('"'+(Join-Path $PSScriptRoot 'artifacts/snes9x_shvc_libretro.dll')+'"'),('"'+(Join-Path $root '../../../SFC-ROM/SuperMarioWorld.sfc')+'"')) -PassThru
  $game.WaitForExit()
} finally {
  if(!$relay.HasExited) { Stop-Process -Id $relay.Id }
}
