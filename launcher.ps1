# 一键启动小鲸鱼：启动服务 + 弹出提示
# -Quiet：开机自启动用，静默启动，不弹提示窗
param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')
$cfg = Get-JingyuConfig
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Show-Tip($text, $color) {
    if ($Quiet) { return }
    $form = $null
    $timer = $null
    $tipFont = $null
    try {
        $form = New-Object System.Windows.Forms.Form
        $form.FormBorderStyle = 'None'
        $form.StartPosition = 'CenterScreen'
        $form.Size = New-Object System.Drawing.Size(360, 120)
        $form.BackColor = [System.Drawing.Color]::FromArgb(28, 32, 48)
        $form.TopMost = $true
        $form.ShowInTaskbar = $false

        $label = New-Object System.Windows.Forms.Label
        $label.Text = $text
        $label.ForeColor = $color
        $tipFont = New-Object System.Drawing.Font("Microsoft YaHei UI", 12, [System.Drawing.FontStyle]::Bold)
        $label.Font = $tipFont
        $label.TextAlign = 'MiddleCenter'
        $label.Dock = 'Fill'
        $form.Controls.Add($label)

        $timer = New-Object System.Windows.Forms.Timer
        $timer.Interval = 2600
        $timer.Add_Tick({ $form.Close() })
        $timer.Start()

        [void]$form.ShowDialog()
        $timer.Stop()
    } catch {
        # 弹窗失败就静默，不影响启动
    } finally {
        if ($timer) { $timer.Stop(); $timer.Dispose() }
        if ($form) { $form.Dispose() }
        if ($tipFont) { $tipFont.Dispose() }
    }
}

$root = $PSScriptRoot
$startScript = Join-Path $root 'start.ps1'
$logFile = Join-Path $root 'logs\launcher.log'

function Write-LauncherLog($msg) {
    try {
        $dir = Split-Path $logFile
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Add-Content -LiteralPath $logFile -Value ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg) -Encoding UTF8
    } catch {}
}

function Test-Port($port) {
    $c = [Net.Sockets.TcpClient]::new()
    try {
        $c.Connect('127.0.0.1', $port)
        return $true
    } catch {
        return $false
    } finally {
        $c.Dispose()
    }
}

try {
    Write-LauncherLog '开始启动'
    $startProcess = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"' + $startScript + '"')) -WindowStyle Hidden -PassThru
    try { $startProcess.WaitForExit(); $startExitCode = $startProcess.ExitCode } finally { $startProcess.Dispose() }
    if ($startExitCode -eq 2) { throw ('QQ 账号使用受限，请在手机 QQ 登录 ' + $cfg.qq + '，按提示恢复后再启动') }
    if ($startExitCode -ne 0) { throw '启动脚本执行失败，请查看日志' }
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) {
        if ((Test-Port $cfg.dashboard_port) -and (Test-Port $cfg.napcat_port)) { $ok = $true; break }
        Start-Sleep -Milliseconds 700
    }
    if (-not $ok) { throw '服务尚未就绪，请查看日志' }
    . (Join-Path $root 'qq-login.ps1')
    $taskLogin = Get-WhaleQQLoginState -Root $root
    if ($taskLogin.isLogin -and $taskLogin.coreReady) {
        Write-LauncherLog '服务已启动，QQ 已在线'
        Show-Tip "小鲸鱼服务已启动`nQQ 已登录" ([System.Drawing.Color]::FromArgb(120, 230, 160))
    } else {
        Write-LauncherLog '服务已启动，QQ 等待登录验证'
        Show-Tip "服务已启动，QQ 尚未登录`n请在打开的页面完成验证" ([System.Drawing.Color]::FromArgb(255, 200, 120))
    }

# 确保托盘图标在跑
$trayScript = Join-Path $root 'tray.ps1'
$trayLock = Join-Path $root 'runtime\tray.lock'
$trayAlive = $false
if (Test-Path $trayLock) {
    $tp = Get-Content $trayLock -Raw
    if ($tp) {
        $tpProc = Get-Process -Id ([int]$tp.Trim()) -ErrorAction SilentlyContinue
        if ($tpProc) { $trayAlive = $true }
    }
}
if (-not $trayAlive -and (Test-Path $trayScript)) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File', ('"' + $trayScript + '"')) -WindowStyle Hidden
    Write-LauncherLog '托盘图标已启动'
}
} catch {
    Write-LauncherLog ("异常: " + $_.Exception.Message)
    Show-Tip "启动出错：$($_.Exception.Message)" ([System.Drawing.Color]::FromArgb(255, 140, 140))
}
