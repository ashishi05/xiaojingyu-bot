param([switch]$Quiet)
. (Join-Path $PSScriptRoot '_lib.ps1')
$deploy=Get-JingyuConfig
$prefs=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime/launcher-settings.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if($Quiet){
    $result=Join-Path $PSScriptRoot ('runtime/launcher-autostart-'+[guid]::NewGuid().ToString('N')+'.json')
    & (Resolve-JingyuPath $deploy.python) (Join-Path $PSScriptRoot 'launcher-control.py') autostart --result $result
    Remove-Item -LiteralPath $result -Force -ErrorAction SilentlyContinue
}
$taskArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-STA','-WindowStyle','Hidden','-File',('"'+(Join-Path $PSScriptRoot 'launcher-ui.ps1')+'"'))
if($Quiet -and $prefs.tray){$taskArgs+='-Tray'}
Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe') -ArgumentList $taskArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
