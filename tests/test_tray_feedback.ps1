$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$root = Split-Path $PSScriptRoot
$text = Get-Content -LiteralPath (Join-Path $root 'tray.ps1') -Raw
$start = $text.IndexOf('$script:operation = $null')
$end = $text.IndexOf('$statusItem = $menu.Items.Add', $start)
$body = $text.Substring($start, $end - $start).Replace('    $form.Show()', "    `$form.StartPosition = 'Manual'`n    `$form.Location = New-Object Drawing.Point(-25000,-25000)`n    `$form.Show()")
. ([scriptblock]::Create($body))
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
$tick=$ast.FindAll({param($node) $node -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $node.Member.Value -eq 'Add_Tick'},$true)[0].Arguments[0].ScriptBlock.GetScriptBlock()
$trayExitEvent=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::AutoReset)
$menuFont=New-Object Drawing.Font('Microsoft YaHei UI',9)
$notify=[pscustomobject]@{Text='';Icon=$null}
$notify | Add-Member ScriptMethod ShowBalloonTip {param($duration,$title,$message,$icon)}
$statusItem=[pscustomobject]@{Text=''}
$startItem=[pscustomobject]@{Enabled=$true}; $stopItem=[pscustomobject]@{Enabled=$true}; $restartItem=[pscustomobject]@{Enabled=$true}
$webItem=[pscustomobject]@{Enabled=$true}; $wakeSettingsItem=[pscustomobject]@{Enabled=$true}; $exitItem=[pscustomobject]@{Enabled=$true}
function Write-Log {param($msg)}
function Start-Process {
    [CmdletBinding()]param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$PassThru)
    if($script:failLaunch){throw 'simulated launch failure'}
    $process=[pscustomobject]@{HasExited=$false}
    $process | Add-Member ScriptMethod Refresh {}
    $process | Add-Member ScriptMethod Dispose {}
    return $process
}
try {
    foreach($case in @(
        @{action='Start';result=@{success=$true;level='success';message='启动完成，QQ 已在线'}},
        @{action='Start';result=@{success=$false;level='warning';message='后台已启动，QQ 等待确认'}},
        @{action='Stop';result=@{success=$false;level='error';message='未能完全关闭'}},
        @{action='Stop';result=@{success=$true;level='success';message='已关闭'}}
    )) {
        $script:servicesStopped=$false; $script:exitDeadline=$null
        Begin-Operation $case.action '测试操作'
        if(-not $script:operation -or $script:feedback.Progress.Style -ne 'Marquee' -or $script:feedback.Close.Enabled -or $startItem.Enabled){throw 'No immediate busy feedback'}
        @{message='正在核对 QQ 在线状态…'} | ConvertTo-Json | Set-Content -LiteralPath ($script:operation.ResultPath + '.progress.json') -Encoding UTF8
        & $tick
        if($script:feedback.Label.Text -notlike '*核对 QQ*'){throw 'Worker phase not displayed'}
        if(-not $script:operation -or $script:feedback.Label.Text -notlike '*已进行*'){throw 'Progress not persistent while worker pending'}
        $resultFile=$script:operation.ResultPath
        $case.result | ConvertTo-Json | Set-Content -LiteralPath $resultFile -Encoding UTF8
        $script:operation.Process.HasExited=$true
        & $tick
        if($script:operation -or -not $script:feedback.Close.Enabled -or $script:feedback.Label.Text -ne $case.result.message){throw 'Completion feedback missing'}
        if((Test-Path -LiteralPath $resultFile) -or (Test-Path -LiteralPath ($resultFile + '.progress.json'))){throw 'Result or progress not cleaned up'}
        if($case.action -eq 'Stop' -and $case.result.success){if(-not $script:servicesStopped -or -not $script:exitDeadline){throw 'Successful stop will not close tray'}}
        elseif(-not $startItem.Enabled){throw 'Failed/completed operation cannot be retried'}
    }
    Begin-Operation 'OpenWeb' '退出期间不应打开新操作'
    if($script:operation){throw 'Tray accepted another operation while exiting'}
    $script:exitDeadline=$null; $script:servicesStopped=$false; $script:failLaunch=$true
    Begin-Operation 'Start' '测试失败'
    if($script:operation -or -not $startItem.Enabled -or $script:feedback.Label.Text -notlike '*无法开始操作*'){throw 'Launch error is hidden'}
    'PASS: immediate busy window, persistent progress, success/warning/error, safe retry, stop lifecycle and launch failure; no service action executed'
} finally {
    $script:operation=$null
    if($script:feedback -and -not $script:feedback.Form.IsDisposed){$script:feedback.Form.Dispose()}
    $menuFont.Dispose(); $trayExitEvent.Dispose()
}
