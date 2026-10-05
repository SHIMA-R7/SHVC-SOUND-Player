param([ValidateSet('BLE','SPP','WIFI')][string]$Transport='BLE')
& (Join-Path $PSScriptRoot 'start_smw_wireless.ps1') -Transport $Transport
