# 小鲸鱼托盘图标：右键可关闭 / 重启 / 打开管理页
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

$root = $PSScriptRoot
. (Join-Path $root '_lib.ps1')
$cfg = Get-JingyuConfig
$lockFile = Join-Path $root 'runtime\tray.lock'
$iconOn = Join-Path $root 'assets\whale_on.ico'
$iconOff = Join-Path $root 'assets\whale_off.ico'
$logFile = Join-Path $root 'logs\launcher.log'

function Write-Log($msg) {
    try {
        Add-Content -LiteralPath $logFile -Value ("[{0}] [tray] {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg) -Encoding UTF8
    } catch {}
}

# 防止重复启动
if (Test-Path $lockFile) {
    $oldPid = Get-Content $lockFile -Raw
    $proc = Get-Process -Id ([int]$oldPid.Trim()) -ErrorAction SilentlyContinue
    if ($proc) { exit 0 }
}
New-Item -ItemType Directory -Path (Split-Path $lockFile) -Force | Out-Null
Set-Content -LiteralPath $lockFile -Value $PID -Encoding UTF8

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

function Get-Running {
    return ((Test-Port $cfg.dashboard_port) -and (Test-Port $cfg.napcat_port))
}

# 托盘图标
$notify = New-Object System.Windows.Forms.NotifyIcon
# Own and reuse both icons; allocating on each timer tick leaks native handles.
try { $runningIcon = New-Object System.Drawing.Icon($iconOn) }
catch { $runningIcon = [System.Drawing.SystemIcons]::Application.Clone() }
try { $stoppedIcon = New-Object System.Drawing.Icon($iconOff) }
catch { $stoppedIcon = [System.Drawing.SystemIcons]::Application.Clone() }
$notify.Icon = $runningIcon
$notify.Text = "小鲸鱼"
$notify.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$menuFont = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$menu.Font = $menuFont

$script:operation = $null
$script:feedback = $null
$script:resultUntil = [datetime]::MinValue
$script:feedbackCloseAt = $null
$script:exitDeadline = $null
$script:exitRequested = $false
$script:servicesStopped = $false

function Show-OperationWindow($label) {
    if ($script:feedback -and -not $script:feedback.Form.IsDisposed) { $script:feedback.Form.Dispose() }
    $form = New-Object Windows.Forms.Form
    $form.Text = '小鲸鱼 · ' + $label
    $form.Font = $menuFont
    $form.AutoScaleMode = 'Dpi'
    $form.ClientSize = New-Object Drawing.Size(430, 160)
    $form.FormBorderStyle = 'FixedDialog'
    $form.StartPosition = 'CenterScreen'
    $form.ControlBox = $false
    $form.MaximizeBox = $false
    $labelControl = New-Object Windows.Forms.Label
    $labelControl.Location = New-Object Drawing.Point(18, 18)
    $labelControl.Size = New-Object Drawing.Size(394, 60)
    $labelControl.Text = $label + '，正在进行…'
    $progress = New-Object Windows.Forms.ProgressBar
    $progress.Location = New-Object Drawing.Point(18, 84)
    $progress.Size = New-Object Drawing.Size(394, 12)
    $progress.Style = 'Marquee'
    $progress.MarqueeAnimationSpeed = 30
    $close = New-Object Windows.Forms.Button
    $close.Text = '关闭'
    $close.Location = New-Object Drawing.Point(332, 116)
    $close.Size = New-Object Drawing.Size(80, 28)
    $close.Enabled = $false
    $close.Add_Click({ $script:feedback.Form.Close() })
    $form.Add_FormClosing({ param($sender, $eventArgs) if ($script:operation) { $eventArgs.Cancel = $true } })
    $form.Controls.AddRange(@($labelControl, $progress, $close))
    $script:feedback = [pscustomobject]@{Form=$form; Label=$labelControl; Progress=$progress; Close=$close}
    $form.Show()
    $form.Activate()
}

function Complete-Operation($result) {
    $action = $script:operation.Action
    $script:operation = $null
    $script:feedback.Progress.MarqueeAnimationSpeed = 0
    $script:feedback.Progress.Style = 'Continuous'
    $script:feedback.Progress.Value = if ($result.success) { 100 } else { 0 }
    $script:feedback.Label.Text = $result.message
    $script:feedback.Label.ForeColor = if ($result.level -eq 'success') { [Drawing.Color]::DarkGreen } elseif ($result.level -eq 'warning') { [Drawing.Color]::DarkOrange } else { [Drawing.Color]::Firebrick }
    $script:feedback.Form.ControlBox = $true
    $script:feedback.Close.Enabled = $true
    foreach ($item in @($startItem,$stopItem,$restartItem,$webItem,$wakeSettingsItem,$exitItem)) { $item.Enabled = $true }
    $script:resultUntil = [datetime]::UtcNow.AddSeconds(12)
    $script:feedbackCloseAt = if ($result.success) { [datetime]::UtcNow.AddSeconds(4) } else { $null }
    $statusItem.Text = $result.message
    $notify.Text = ('小鲸鱼 · ' + $result.message).Substring(0, [Math]::Min(63, ('小鲸鱼 · ' + $result.message).Length))
    $tip = if ($result.level -eq 'success') { [Windows.Forms.ToolTipIcon]::Info } else { [Windows.Forms.ToolTipIcon]::Warning }
    $notify.ShowBalloonTip(3000, '小鲸鱼', $result.message, $tip)
    Write-Log ('操作结果：' + $result.message)
    if ($action -eq 'Stop' -and $result.success) {
        $script:servicesStopped = $true
        $script:exitDeadline = [datetime]::UtcNow.AddSeconds(3)
        foreach ($item in @($startItem,$stopItem,$restartItem,$webItem,$wakeSettingsItem,$exitItem)) { $item.Enabled = $false }
    }
    if ($script:exitRequested) { [Windows.Forms.Application]::Exit() }
}

function Begin-Operation($action, $label) {
    if ($script:exitDeadline -or $script:exitRequested) { return }
    if ($script:operation) {
        $script:feedback.Form.Activate()
        return
    }
    $script:feedbackCloseAt = $null
    $resultFile = Join-Path $root ('runtime\ui-' + [guid]::NewGuid().ToString('N') + '.json')
    $script:operation = [pscustomobject]@{Action=$action; Label=$label; Process=$null; ResultPath=$resultFile; Started=[datetime]::UtcNow}
    Show-OperationWindow $label
    foreach ($item in @($startItem,$stopItem,$restartItem,$webItem,$wakeSettingsItem,$exitItem)) { $item.Enabled = $false }
    $statusItem.Text = $label + '…'
    $notify.Text = '小鲸鱼 · ' + $label + '…'
    $notify.ShowBalloonTip(2000, '小鲸鱼', $label + '，正在进行…', [Windows.Forms.ToolTipIcon]::Info)
    try {
        $worker = Join-Path $root 'maintenance\ui-operation.ps1'
        $script:operation.Process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"' + $worker + '"'),'-Action',$action,'-ResultPath',('"' + $resultFile + '"')) -WorkingDirectory $root -WindowStyle Hidden -PassThru -ErrorAction Stop
    } catch {
        Complete-Operation ([pscustomobject]@{success=$false; level='error'; message=('无法开始操作：' + $_.Exception.Message)})
    }
}

$statusItem = $menu.Items.Add("状态：检测中…")
$statusItem.Enabled = $false
[void]$menu.Items.Add("-")

$startItem = $menu.Items.Add("启动小鲸鱼")
$startItem.Add_Click({ Begin-Operation 'Start' '正在启动小鲸鱼' })

$stopItem = $menu.Items.Add("关闭小鲸鱼")
$stopItem.Add_Click({ Begin-Operation 'Stop' '正在关闭小鲸鱼' })

$restartItem = $menu.Items.Add("重启小鲸鱼")
$restartItem.Add_Click({ Begin-Operation 'Restart' '正在重启小鲸鱼' })

[void]$menu.Items.Add("-")
$webItem = $menu.Items.Add("打开管理页面")
$webItem.Add_Click({ Begin-Operation 'OpenWeb' '正在打开管理页面' })

[void]$menu.Items.Add("-")
$wakeSettingsItem = $menu.Items.Add("定时唤醒设置…")
$wakeSettingsItem.Add_Click({ Begin-Operation 'OpenWake' '正在打开定时唤醒设置' })

[void]$menu.Items.Add("-")
$exitItem = $menu.Items.Add("退出并关闭小鲸鱼")
$exitItem.Add_Click({ Begin-Operation 'Stop' '正在关闭小鲸鱼并退出托盘' })

$notify.ContextMenuStrip = $menu
$notify.Add_DoubleClick({ Begin-Operation 'OpenWeb' '正在打开管理页面' })

$trayExitEvent = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::AutoReset, 'Local\WhaleTrayExit')

# 定时刷新状态
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1000
$timer.Add_Tick({
    if ($trayExitEvent.WaitOne(0)) {
        if ($script:operation) { $script:exitRequested = $true }
        else { [System.Windows.Forms.Application]::Exit(); return }
    }
    if ($script:feedbackCloseAt -and [datetime]::UtcNow -ge $script:feedbackCloseAt) {
        if ($script:feedback -and -not $script:feedback.Form.IsDisposed) { $script:feedback.Form.Close() }
        $script:feedbackCloseAt = $null
    }
    if ($script:exitDeadline -and [datetime]::UtcNow -ge $script:exitDeadline) { [System.Windows.Forms.Application]::Exit(); return }
    if ($script:operation) {
        $process = $script:operation.Process
        if ($process) {
            $process.Refresh()
            if ($process.HasExited) {
                $resultPath = $script:operation.ResultPath
                try {
                    $result = Get-Content -LiteralPath $resultPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                    if ($result.success -isnot [bool] -or $result.level -notin @('success','warning','error') -or -not $result.message) { throw 'No operation result' }
                } catch { $result = [pscustomobject]@{success=$false; level='error'; message='执行结束但未收到结果，请查看 logs/launcher.log。'} }
                Remove-Item -LiteralPath $resultPath,($resultPath + '.progress.json') -Force -ErrorAction SilentlyContinue
                $process.Dispose()
                Complete-Operation $result
            } else {
                $elapsed = [int]([datetime]::UtcNow - $script:operation.Started).TotalSeconds
                $phase = $script:operation.Label
                try {
                    $progressPath = $script:operation.ResultPath + '.progress.json'
                    if (Test-Path -LiteralPath $progressPath) {
                        $phaseResult = Get-Content -LiteralPath $progressPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                        if ($phaseResult.message) { $phase = [string]$phaseResult.message }
                    }
                } catch {}
                $statusItem.Text = $phase + '（' + $elapsed + ' 秒）'
                $script:feedback.Label.Text = $phase + "`n已进行 " + $elapsed + ' 秒，请稍候'
            }
        }
        return
    }
    if ([datetime]::UtcNow -lt $script:resultUntil) { return }
    $running = Get-Running
    if ($running) {
        $statusItem.Text = "状态：运行中"
        $notify.Text = "小鲸鱼 · 运行中"
        $notify.Icon = $runningIcon
    } else {
        $statusItem.Text = "状态：已停止"
        $notify.Text = "小鲸鱼 · 已停止"
        $notify.Icon = $stoppedIcon
    }
})
$timer.Start()

Write-Log "托盘已启动 (PID $PID)"
try {
    if (-not (Get-Running)) {
        Begin-Operation 'Start' '正在启动小鲸鱼'
    }
    [System.Windows.Forms.Application]::Run()
} finally {
    $timer.Stop()
    if (-not $script:servicesStopped) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File (Join-Path $root 'stop.ps1') -KeepTray *> $null
        if ($LASTEXITCODE -ne 0) { Write-Log '托盘退出时服务未完全停止，请检查日志' }
        else { Write-Log '托盘退出，已关闭小鲸鱼' }
    }
    if ($script:feedback -and -not $script:feedback.Form.IsDisposed) { $script:feedback.Form.Dispose() }
    $notify.Visible = $false
    $notify.Dispose()
    $menu.Dispose()
    $menuFont.Dispose()
    $runningIcon.Dispose()
    $stoppedIcon.Dispose()
    $timer.Dispose()
    $trayExitEvent.Dispose()
    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
}
