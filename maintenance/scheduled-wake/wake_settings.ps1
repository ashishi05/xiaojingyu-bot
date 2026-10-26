# Edit the existing task; opening this window never changes its schedule.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$taskName = '小鲸鱼-定时唤醒'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$workerScript = Join-Path $root 'maintenance\ui-operation.ps1'
$script:saveOperation = $null
$script:readingSchedule = $false
$saveTimer = New-Object Windows.Forms.Timer
$saveTimer.Interval = 200
$mutex = [Threading.Mutex]::new($false, 'Local\WhaleWakeSettings')
$ownsMutex = $false
try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) {
    [void][Windows.Forms.MessageBox]::Show('定时唤醒设置已打开，可以用 Alt+Tab 切换到该窗口。', '小鲸鱼')
    $mutex.Dispose()
    return
}
$form = New-Object Windows.Forms.Form
$font = New-Object Drawing.Font('Microsoft YaHei UI', 10)
try {
    $form.Text = '小鲸鱼 · 定时唤醒设置'
    $form.Font = $font
    $form.AutoScaleMode = 'Dpi'
    $form.ClientSize = New-Object Drawing.Size(530, 458)
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.StartPosition = 'CenterScreen'

    $layout = New-Object Windows.Forms.TableLayoutPanel
    $layout.Dock = 'Fill'
    $layout.Padding = New-Object Windows.Forms.Padding(22, 16, 22, 16)
    $layout.ColumnCount = 2
    $layout.RowCount = 9
    [void]$layout.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Absolute', 125)))
    [void]$layout.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent', 100)))
    foreach ($height in @(50, 38, 40, 40, 40, 45, 62, 66, 45)) {
        [void]$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute', $height)))
    }
    $form.Controls.Add($layout)

    $intro = New-Object Windows.Forms.Label
    $intro.Text = '按计划叫醒电脑，随后检查小鲸鱼并自动启动或恢复登录'
    $intro.Dock = 'Fill'
    $layout.Controls.Add($intro, 0, 0)
    $layout.SetColumnSpan($intro, 2)
    $enabledBox = New-Object Windows.Forms.CheckBox
    $enabledBox.Text = '启用定时唤醒'
    $enabledBox.AutoSize = $true
    $layout.Controls.Add($enabledBox, 0, 1)
    $layout.SetColumnSpan($enabledBox, 2)

    $repeatLabel = New-Object Windows.Forms.Label
    $repeatLabel.Text = '重复'
    $repeatLabel.AutoSize = $true
    $repeatLabel.Margin = New-Object Windows.Forms.Padding(0, 6, 0, 0)
    $layout.Controls.Add($repeatLabel, 0, 2)
    $repeatBox = New-Object Windows.Forms.ComboBox
    $repeatBox.DropDownStyle = 'DropDownList'
    $repeatBox.Dock = 'Top'
    [void]$repeatBox.Items.Add('仅一次')
    [void]$repeatBox.Items.Add('每天')
    $repeatBox.SelectedIndex = 0
    $layout.Controls.Add($repeatBox, 1, 2)

    $dateLabel = New-Object Windows.Forms.Label
    $dateLabel.Text = '日期（仅一次）'
    $dateLabel.AutoSize = $true
    $dateLabel.Margin = New-Object Windows.Forms.Padding(0, 6, 0, 0)
    $layout.Controls.Add($dateLabel, 0, 3)
    $datePicker = New-Object Windows.Forms.DateTimePicker
    $datePicker.Format = 'Custom'
    $datePicker.CustomFormat = 'yyyy-MM-dd'
    $datePicker.Dock = 'Top'
    $datePicker.Value = (Get-Date).Date.AddDays(1)
    $layout.Controls.Add($datePicker, 1, 3)

    $timeLabel = New-Object Windows.Forms.Label
    $timeLabel.Text = '时间（24 小时）'
    $timeLabel.AutoSize = $true
    $timeLabel.Margin = New-Object Windows.Forms.Padding(0, 6, 0, 0)
    $layout.Controls.Add($timeLabel, 0, 4)
    $timePicker = New-Object Windows.Forms.DateTimePicker
    $timePicker.Format = 'Custom'
    $timePicker.CustomFormat = 'HH:mm'
    $timePicker.ShowUpDown = $true
    $timePicker.Dock = 'Top'
    $timePicker.Value = (Get-Date).Date.AddHours(10)
    $layout.Controls.Add($timePicker, 1, 4)
    $repeatBox.Add_SelectedIndexChanged({ $datePicker.Enabled = ($repeatBox.SelectedIndex -eq 0) })

    $nextLabel = New-Object Windows.Forms.Label
    $nextLabel.Dock = 'Fill'
    $layout.Controls.Add($nextLabel, 0, 5)
    $layout.SetColumnSpan($nextLabel, 2)
    $note = New-Object Windows.Forms.Label
    $note.Text = "电脑须保持睡眠、Windows 用户已登录（锁屏可以）。`n关机不能靠此任务开机；唤醒后保持系统运行 14 小时，显示器可关闭。"
    $note.ForeColor = [Drawing.Color]::DimGray
    $note.Dock = 'Fill'
    $layout.Controls.Add($note, 0, 6)
    $layout.SetColumnSpan($note, 2)
    $feedbackPanel = New-Object Windows.Forms.Panel
    $feedbackPanel.Dock = 'Fill'
    $progress = New-Object Windows.Forms.ProgressBar
    $progress.Dock = 'Bottom'
    $progress.Height = 7
    $progress.Visible = $false
    $progress.MarqueeAnimationSpeed = 30
    $feedbackPanel.Controls.Add($progress)
    $statusLabel = New-Object Windows.Forms.Label
    $statusLabel.Dock = 'Fill'
    $statusLabel.Text = '尚未修改设置'
    $statusLabel.AutoEllipsis = $true
    $feedbackPanel.Controls.Add($statusLabel)
    $statusLabel.BringToFront()
    $layout.Controls.Add($feedbackPanel, 0, 7)
    $layout.SetColumnSpan($feedbackPanel, 2)
    $feedbackTip = New-Object Windows.Forms.ToolTip

    $buttons = New-Object Windows.Forms.FlowLayoutPanel
    $buttons.Dock = 'Fill'
    $buttons.FlowDirection = 'RightToLeft'
    $save = New-Object Windows.Forms.Button
    $save.Text = '保存'
    $save.AutoSize = $true
    $close = New-Object Windows.Forms.Button
    $close.Text = '关闭'
    $close.AutoSize = $true
    $close.Add_Click({ $form.Close() })
    $buttons.Controls.Add($close)
    $buttons.Controls.Add($save)
    $layout.Controls.Add($buttons, 0, 8)
    $layout.SetColumnSpan($buttons, 2)
    $form.CancelButton = $close

    function Show-UnsavedSchedule {
        if ($script:readingSchedule -or $script:saveOperation) { return }
        $statusLabel.Text = '设置已更改，点击“保存”后生效'
        $statusLabel.ForeColor = [Drawing.Color]::DimGray
        $progress.Visible = $false
    }
    $enabledBox.Add_CheckedChanged({ Show-UnsavedSchedule })
    $repeatBox.Add_SelectedIndexChanged({ Show-UnsavedSchedule })
    $datePicker.Add_ValueChanged({ Show-UnsavedSchedule })
    $timePicker.Add_ValueChanged({ Show-UnsavedSchedule })

    function Read-WakeSchedule {
        $script:readingSchedule = $true
        try {
            $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            if (-not $existing) {
                $enabledBox.Checked = $false
                $nextLabel.Text = '当前没有唤醒任务，保存后才会创建'
                return
            }
            $enabledBox.Checked = ($existing.State -ne 'Disabled')
            $trigger = @($existing.Triggers)[0]
            if ($trigger) {
                $when = [datetime]::Parse($trigger.StartBoundary).ToLocalTime()
                $datePicker.Value = $when.Date
                $timePicker.Value = $when
                $repeatBox.SelectedIndex = if ($trigger.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger') { 1 } else { 0 }
            }
            $info = Get-ScheduledTaskInfo -TaskName $taskName
            if ($enabledBox.Checked -and $info.NextRunTime.Year -gt 2000) {
                $nextLabel.Text = '下次唤醒：' + $info.NextRunTime.ToString('yyyy-MM-dd HH:mm')
            } else { $nextLabel.Text = '当前状态：定时唤醒已停用' }
        } finally { $script:readingSchedule = $false }
    }

    $saveTimer.Add_Tick({
        if (-not $script:saveOperation) { return }
        if (-not $script:saveOperation.Process.HasExited) {
            $elapsed = [int]((Get-Date) - $script:saveOperation.StartedAt).TotalSeconds
            $statusLabel.Text = $script:saveOperation.Label + '（已用 ' + $elapsed + ' 秒）'
            return
        }
        $saveTimer.Stop()
        $succeeded = $false
        try {
            if (-not (Test-Path -LiteralPath $script:saveOperation.ResultPath)) {
                throw '没有收到保存结果，请重试；如仍失败，请查看启动日志'
            }
            $result = Get-Content -LiteralPath $script:saveOperation.ResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($result.success -isnot [bool] -or -not $result.message) { throw '保存结果格式不正确，请重试' }
            if ($result.success) {
                Read-WakeSchedule
                $succeeded = $true
                $statusLabel.ForeColor = [Drawing.Color]::DarkGreen
                $statusLabel.Text = '✓ ' + $result.message
            } else {
                $statusLabel.ForeColor = if ($result.level -eq 'warning') { [Drawing.Color]::DarkOrange } else { [Drawing.Color]::Firebrick }
                $statusLabel.Text = '未完成：' + $result.message
            }
        } catch {
            $statusLabel.ForeColor = [Drawing.Color]::Firebrick
            $statusLabel.Text = '保存失败：' + $_.Exception.Message
        } finally {
            $feedbackTip.SetToolTip($statusLabel, $statusLabel.Text)
            Remove-Item -LiteralPath $script:saveOperation.ResultPath -Force -ErrorAction SilentlyContinue
            if ($script:saveOperation.Process -is [Diagnostics.Process]) { $script:saveOperation.Process.Dispose() }
            $script:saveOperation = $null
            $progress.Style = 'Continuous'
            $progress.Value = if ($succeeded) { 100 } else { 0 }
            $form.UseWaitCursor = $false
            foreach ($control in @($enabledBox, $repeatBox, $timePicker, $save, $close)) { $control.Enabled = $true }
            $datePicker.Enabled = ($repeatBox.SelectedIndex -eq 0)
            $save.Text = '保存'
        }
    })
    $save.Add_Click({
        if ($script:saveOperation) { return }
        try {
            foreach ($control in @($enabledBox, $repeatBox, $datePicker, $timePicker, $save, $close)) { $control.Enabled = $false }
            $save.Text = '保存中…'
            $form.UseWaitCursor = $true
            $statusLabel.Text = if ($enabledBox.Checked) { '正在保存唤醒安排…' } else { '正在停用定时唤醒…' }
            $statusLabel.ForeColor = [Drawing.Color]::DarkSlateBlue
            $progress.Visible = $true
            $progress.Style = 'Marquee'
            $feedbackTip.SetToolTip($statusLabel, $statusLabel.Text)
            $form.Refresh()
            $resultPath = Join-Path $root ('runtime\ui-' + [guid]::NewGuid().ToString('N') + '.json')
            $arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $workerScript + '" -Action SaveWake -ResultPath "' + $resultPath + '"'
            if (-not $enabledBox.Checked) { $arguments += ' -Disable' }
            else {
                $arguments += ' -Date ' + $datePicker.Value.ToString('yyyy-MM-dd') + ' -Time ' + $timePicker.Value.ToString('HH:mm')
                if ($repeatBox.SelectedIndex -eq 1) { $arguments += ' -Daily' }
            }
            $process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -PassThru -ErrorAction Stop
            $script:saveOperation = [pscustomobject]@{Process=$process; ResultPath=$resultPath; StartedAt=(Get-Date); Label=$statusLabel.Text}
            $saveTimer.Start()
        } catch {
            $statusLabel.ForeColor = [Drawing.Color]::Firebrick
            $statusLabel.Text = '保存失败：' + $_.Exception.Message
            $feedbackTip.SetToolTip($statusLabel, $statusLabel.Text)
            $progress.Style = 'Continuous'
            $progress.Value = 0
            $form.UseWaitCursor = $false
            foreach ($control in @($enabledBox, $repeatBox, $timePicker, $save, $close)) { $control.Enabled = $true }
            $datePicker.Enabled = ($repeatBox.SelectedIndex -eq 0)
            $save.Text = '保存'
        }
    })
    $form.Add_FormClosing({
        param($sender, $eventArgs)
        if ($script:saveOperation) {
            $eventArgs.Cancel = $true
            $statusLabel.Text = '正在保存，请稍候完成后再关闭'
        }
    })
    Read-WakeSchedule
    [void]$form.ShowDialog()
} finally {
    $saveTimer.Stop()
    $saveTimer.Dispose()
    if ($feedbackTip) { $feedbackTip.Dispose() }
    $form.Dispose()
    $font.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
