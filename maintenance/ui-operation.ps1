param(
    [Parameter(Mandatory=$true)][ValidateSet('Start','Stop','Restart','OpenWeb','OpenWake','SaveWake')][string]$Action,
    [Parameter(Mandatory=$true)][string]$ResultPath,
    [string]$Date,
    [string]$Time,
    [switch]$Daily,
    [switch]$Disable
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$runtime = [IO.Path]::GetFullPath((Join-Path $root 'runtime')) + [IO.Path]::DirectorySeparatorChar
$resultFile = [IO.Path]::GetFullPath($ResultPath)
if (-not $resultFile.StartsWith($runtime, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($resultFile) -notmatch '^ui-[a-f0-9]+\.json$') { throw 'Invalid UI result path' }
$powerShell = Join-Path $PSHOME 'powershell.exe'
function Test-Port($port) {
    $client = [Net.Sockets.TcpClient]::new()
    try { $client.Connect('127.0.0.1', $port); return $true }
    catch { return $false }
    finally { $client.Dispose() }
}
function Get-Online {
    if (-not ((Test-Port 6185) -and (Test-Port 6099))) { return $false }
    try {
        . (Join-Path $root 'qq-login.ps1')
        $state = Get-WhaleQQLoginState -Root $root
        return [bool]($state.isLogin -and $state.coreReady)
    } catch { return $false }
}
function Set-OperationPhase($message) {
    try { @{message=$message} | ConvertTo-Json -Compress | Set-Content -LiteralPath ($resultFile + '.progress.json') -Encoding UTF8 -ErrorAction Stop } catch {}
}
function Invoke-ServiceScript($Name, [switch]$KeepTray) {
    $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"' + (Join-Path $root $Name) + '"'))
    if ($KeepTray) { $arguments += '-KeepTray' }
    $child = Start-Process -FilePath $powerShell -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -PassThru -ErrorAction Stop
    try {
        # Wait for this script only; a native pipeline or -Wait also waits for background descendants.
        $child.WaitForExit()
        return $child.ExitCode
    } finally { $child.Dispose() }
}
$result = @{success=$true; level='success'; message='操作完成'}
try {
    switch ($Action) {
        'Stop' {
            Set-OperationPhase '正在关闭机器人服务…'
            $code = Invoke-ServiceScript 'stop.ps1' -KeepTray
            if ($code -ne 0 -or (Test-Port 6185) -or (Test-Port 6099) -or (Test-Port 6199)) { throw '未能完全关闭，请查看 logs/launcher.log；托盘会保留，方便重试。' }
            $result.message = '小鲸鱼已关闭，托盘即将退出'
        }
        { $_ -in 'Start','Restart' } {
            if ($Action -eq 'Start' -and (Get-Online)) { $result.message = '小鲸鱼已在运行，QQ 已在线'; break }
            if ($Action -eq 'Restart') {
                Set-OperationPhase '正在关闭旧服务…'
                $stopCode = Invoke-ServiceScript 'stop.ps1' -KeepTray
                if ($stopCode -ne 0) { throw '未能完全停止，已取消重启；请查看 logs/launcher.log。' }
            }
            Set-OperationPhase '正在启动服务并恢复 QQ 登录…'
            $code = Invoke-ServiceScript 'start.ps1'
            if ($code -ne 0 -and $code -ne 2) { throw '启动失败，请查看 logs/launcher.log 和 logs/astrbot.err.log。' }
            Set-OperationPhase '正在核对 QQ 在线状态…'
            if (Get-Online) {
                $result.message = if ($Action -eq 'Restart') { '重启完成，QQ 已在线' } else { '启动完成，QQ 已在线' }
            } elseif ((Test-Port 6185) -and (Test-Port 6099)) {
                $result.success = $false
                $result.level = 'warning'
                $result.message = '后台已启动，QQ 尚未在线。请打开管理页面完成手机验证。'
            } else { throw '服务尚未就绪，请查看 logs/launcher.log。' }
        }
        'OpenWeb' {
            $url = 'http://127.0.0.1:6099/webui'
            try {
                $cfg = Get-Content -LiteralPath (Join-Path $root 'NapCat\napcat\config\webui.json') -Raw | ConvertFrom-Json
                if ($cfg.token) { $url += '?token=' + [Uri]::EscapeDataString($cfg.token) }
            } catch {}
            try { Start-Process $url -ErrorAction Stop | Out-Null }
            catch { throw '未能打开浏览器，请检查默认浏览器设置。' }
            $result.message = '已请求浏览器打开管理页面'
        }
        'OpenWake' {
            $script = Join-Path $root 'maintenance\scheduled-wake\wake_settings.ps1'
            $process = Start-Process -FilePath $powerShell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-STA','-File',('"' + $script + '"')) -WorkingDirectory $root -WindowStyle Hidden -PassThru
            $ready = $false
            for ($index=0; $index -lt 40; $index++) {
                $process.Refresh()
                if ($process.HasExited) {
                    if ($process.ExitCode -ne 0) { throw '定时唤醒窗口打开失败，请检查脚本或重新启动托盘。' }
                    break
                }
                if ($process.MainWindowHandle -ne [IntPtr]::Zero) { $ready = $true; break }
                Start-Sleep -Milliseconds 250
            }
            $result.message = if ($ready) { '定时唤醒设置已打开' } else { '已请求打开设置，可用 Alt+Tab 切换查看' }
        }
        'SaveWake' {
            $taskName = '小鲸鱼-定时唤醒'
            if ($Disable) {
                if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
                    Disable-ScheduledTask -TaskName $taskName | Out-Null
                    if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Disabled') { throw '任务尚未停用，请重试。' }
                }
                $result.message = '已停用定时唤醒'
            } else {
                $setup = Join-Path $root 'maintenance\scheduled-wake\setup-task.ps1'
                if ($Daily) { & $setup -Daily -Time $Time | Out-Null }
                else { & $setup -Date $Date -Time $Time | Out-Null }
                $task = Get-ScheduledTask -TaskName $taskName
                $next = (Get-ScheduledTaskInfo -TaskName $taskName).NextRunTime
                if ($task.State -eq 'Disabled' -or -not $task.Settings.WakeToRun) { throw '保存后核对失败，请重试。' }
                $result.message = '已保存，下次唤醒：' + $next.ToString('yyyy-MM-dd HH:mm')
            }
        }
    }
} catch {
    $result = @{success=$false; level='error'; message=$_.Exception.Message}
}
$result | ConvertTo-Json -Compress | Set-Content -LiteralPath $resultFile -Encoding UTF8
if ($result.level -eq 'error') { exit 1 }
if ($result.level -eq 'warning') { exit 2 }
exit 0
