$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
. (Join-Path $root '_lib.ps1')
$deploy=Get-JingyuConfig
$python=Resolve-JingyuPath $deploy.python
$astrbot=Resolve-JingyuPath $deploy.astrbot_dir
if(-not(Test-Path -LiteralPath $python) -or -not(Test-Path -LiteralPath (Join-Path $astrbot 'data/cmd_config.json'))){throw '请先安装 AstrBot，并配置本机 config.json'}
& $python -c 'import psutil, requests'
if($LASTEXITCODE -ne 0){throw '请在 AstrBot 虚拟环境安装 psutil 和 requests 后重试'}
foreach($folder in @('runtime','logs','backups')){New-Item -ItemType Directory -Path (Join-Path $root $folder) -Force | Out-Null}
$backup=Join-Path $root ('backups/control-center-'+(Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('launcher.ps1','tray.ps1','launcher-ui.ps1','launcher-control.py','launcher-service.ps1','setup_credentials.py')){
    $target=Join-Path $root $name
    if(Test-Path -LiteralPath $target){Copy-Item -LiteralPath $target -Destination $backup}
    if($name -ne 'tray.ps1'){Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $target}
}
$tray='Start-Process -FilePath (Join-Path $env:SystemRoot ''System32/WindowsPowerShell/v1.0/powershell.exe'') -ArgumentList @(''-NoProfile'',''-ExecutionPolicy'',''Bypass'',''-STA'',''-WindowStyle'',''Hidden'',''-File'',(''"''+(Join-Path $PSScriptRoot ''launcher-ui.ps1'')+''"''),''-Tray'') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden'
[IO.File]::WriteAllText((Join-Path $root 'tray.ps1'),$tray,[Text.UTF8Encoding]::new($true))
$plugin=Join-Path $astrbot 'data/plugins/launcher_monitor'
if(Test-Path -LiteralPath $plugin){Copy-Item -LiteralPath $plugin -Destination (Join-Path $backup 'launcher_monitor') -Recurse}
New-Item -ItemType Directory -Path $plugin -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'monitor.py') -Destination (Join-Path $plugin 'main.py')
@{root=$root}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $plugin 'launcher_root.json') -Encoding UTF8
Set-Content -LiteralPath (Join-Path $plugin 'metadata.yaml') -Encoding UTF8 -Value "name: launcher_monitor`ndesc: 控制中心状态采集`nauthor: Local`nversion: 1.0.0"
$prefsPath=Join-Path $root 'runtime/launcher-settings.json'
if(-not(Test-Path -LiteralPath $prefsPath)){
    @{official=$false;personal=$false;boot=$false;tray=$true;reconnect=$false}|ConvertTo-Json|Set-Content -LiteralPath $prefsPath -Encoding UTF8
}
if(-not(Test-Path -LiteralPath (Join-Path $root 'runtime/launcher-dashboard-login.dpapi'))){
    & $python (Join-Path $root 'setup_credentials.py')
    if($LASTEXITCODE -ne 0){throw '管理凭据未配置完成，请重新执行安装'}
}
Write-Host "安装完成，原入口备份于：$backup"
Write-Host '请启动 AstrBot，在插件页面重载 launcher_monitor，再使用 启动机器人.cmd。'
