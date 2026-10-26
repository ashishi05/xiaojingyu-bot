$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Import-Module ScheduledTasks
$root = Split-Path $PSScriptRoot
$uiPath = Join-Path $root 'maintenance\scheduled-wake\wake_settings.ps1'
$before = Export-ScheduledTask -TaskName '小鲸鱼-定时唤醒'
$global:WakeFeedbackLaunches = @()
$global:WakeFeedbackThrowLaunch = $false
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru, $ErrorAction)
    if ($global:WakeFeedbackThrowLaunch) { throw '模拟启动失败' }
    $global:WakeFeedbackLaunches += $ArgumentList
    $resultPath = [regex]::Match($ArgumentList, '-ResultPath "([^"]+)"').Groups[1].Value
    if (-not $resultPath) { throw 'Worker result path missing' }
    $global:WakeFeedbackReply | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    $global:WakeFeedbackProcess = [pscustomobject]@{HasExited=$false}
    return $global:WakeFeedbackProcess
}
$source = Get-Content -LiteralPath $uiPath -Raw -Encoding UTF8
$source = $source.Replace('$PSScriptRoot', ("'" + (Split-Path $uiPath) + "'"))
$source = $source.Replace('Local\WhaleWakeSettings', ('Local\WhaleWakeSettingsFeedbackTest' + [guid]::NewGuid().ToString('N')))
$body = @'
    $form.StartPosition = 'Manual'
    $form.Location = New-Object Drawing.Point(-25000, -25000)
    $form.Show()
    [Windows.Forms.Application]::DoEvents()
    function Save-FeedbackPreview($name) {
        $bitmap = New-Object Drawing.Bitmap($form.Width, $form.Height)
        try {
            $form.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
            $bitmap.Save((Join-Path $env:TEMP $name))
        } finally { $bitmap.Dispose() }
    }
    function Complete-FakeSave {
        $global:WakeFeedbackProcess.HasExited = $true
        $deadline = (Get-Date).AddSeconds(3)
        while ($script:saveOperation -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 30
            [Windows.Forms.Application]::DoEvents()
        }
        if ($script:saveOperation) { throw 'UI did not finish processing the worker' }
    }
    if ($global:WakeFeedbackLaunches.Count) { throw 'Opening UI launched a save' }
    $originalNext = $nextLabel.Text
    $timePicker.Value = $timePicker.Value.AddMinutes(1)
    if ($statusLabel.Text -notlike '*更改*') { throw 'Changed inputs have no pending-save feedback' }
    if ($global:WakeFeedbackLaunches.Count) { throw 'Editing UI launched a save before clicking Save' }
    $global:WakeFeedbackReply = @{success=$true;level='success';message='已保存：测试结果，不改动真实任务'}
    $save.PerformClick()
    if (-not $script:saveOperation -or $save.Enabled -or $close.Enabled) { throw 'Save has no busy/duplicate-click protection' }
    if ($statusLabel.Text -notlike '正在*' -or $progress.Style -ne 'Marquee' -or -not $progress.Visible) { throw 'Persistent progress feedback missing' }
    Save-FeedbackPreview 'wake-save-progress.png'
    $form.Close()
    if (-not $form.Visible) { throw 'Form closed during a pending save' }
    Complete-FakeSave
    if ($statusLabel.ForeColor -ne [Drawing.Color]::DarkGreen -or $progress.Value -ne 100 -or -not $save.Enabled) { throw 'Successful save has no durable result' }
    if ($nextLabel.Text -ne $originalNext) { throw 'Mock save changed the real schedule view' }
    Save-FeedbackPreview 'wake-save-complete.png'
    $global:WakeFeedbackReply = @{success=$false;level='error';message='访问被拒绝，请检查任务权限'}
    $save.PerformClick()
    Complete-FakeSave
    if ($statusLabel.Text -notlike '*访问被拒绝*' -or $statusLabel.ForeColor -ne [Drawing.Color]::Firebrick -or -not $save.Enabled) { throw 'Failed save has no actionable feedback' }
    Save-FeedbackPreview 'wake-save-error.png'
    $global:WakeFeedbackReply = @{success='true';level='success';message='无效的结果'}
    $save.PerformClick()
    Complete-FakeSave
    if ($statusLabel.Text -notlike '*格式*' -or $statusLabel.ForeColor -ne [Drawing.Color]::Firebrick) { throw 'Malformed result reported success' }
    $global:WakeFeedbackThrowLaunch = $true
    $save.PerformClick()
    if ($script:saveOperation -or -not $save.Enabled -or $statusLabel.Text -notlike '*模拟启动失败*') { throw 'Worker launch failure left UI stuck' }
    $form.Close()
'@
$source = $source.Replace('[void]$form.ShowDialog()', $body)
& ([scriptblock]::Create($source))
$after = Export-ScheduledTask -TaskName '小鲸鱼-定时唤醒'
if ($before -ne $after) { throw 'UI feedback tests changed the scheduled task' }
'PASS: immediate saving, persistent progress, blocked duplicate/close, success, error, malformed response and launch failure; real task unchanged'
