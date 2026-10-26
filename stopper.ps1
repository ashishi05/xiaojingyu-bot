# 一键关闭小鲸鱼：停服务 + 兜底清理 + 弹提示
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Show-Tip($text, $color) {
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
        $label.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 12, [System.Drawing.FontStyle]::Bold)
        $label.TextAlign = 'MiddleCenter'
        $label.Dock = 'Fill'
        $form.Controls.Add($label)

        $timer = New-Object System.Windows.Forms.Timer
        $timer.Interval = 2600
        $timer.Add_Tick({ $form.Close() })
        $timer.Start()

        [void]$form.ShowDialog()
        $timer.Stop()
    } catch {}
}

$root = $PSScriptRoot
$stopScript = Join-Path $root 'stop.ps1'
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
    Write-LauncherLog '开始关闭'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $stopScript *> $null
    if ($LASTEXITCODE -ne 0) { throw '未能完全关闭，请查看日志' }
    Write-LauncherLog '服务已关闭，托盘同步退出'
    Show-Tip "小鲸鱼已关闭`n托盘同步退出" ([System.Drawing.Color]::FromArgb(160, 180, 220))
} catch {
    Write-LauncherLog ("异常: " + $_.Exception.Message)
    Show-Tip "关闭出错：$($_.Exception.Message)" ([System.Drawing.Color]::FromArgb(255, 140, 140))
}
