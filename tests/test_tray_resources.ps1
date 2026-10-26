$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot
$taskPath = Join-Path $taskRoot 'tray.ps1'
$taskTokens = $null
$taskErrors = $null
$taskAst = [System.Management.Automation.Language.Parser]::ParseFile($taskPath, [ref]$taskTokens, [ref]$taskErrors)
if ($taskErrors.Count) { throw 'Tray script has syntax errors' }
$taskTick = $taskAst.FindAll({param($node) $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and $node.Member.Value -eq 'Add_Tick'}, $true)[0].Arguments[0].ScriptBlock
$taskAllocations = $taskTick.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'New-Object' -and $node.Extent.Text -match 'System.Drawing.Icon'}, $true)
if ($taskAllocations.Count) { throw 'Timer allocates new icons on every tick' }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$iconOn = Join-Path $taskRoot 'assets\whale_on.ico'
$iconOff = Join-Path $taskRoot 'assets\whale_off.ico'
$taskText = Get-Content -LiteralPath $taskPath -Raw
$taskStart = $taskText.IndexOf('$notify = New-Object System.Windows.Forms.NotifyIcon')
$taskEnd = $taskText.IndexOf('$notify.Text =', $taskStart)
# Dot-source initialization so its icon objects remain in this scope.
. ([scriptblock]::Create($taskText.Substring($taskStart, $taskEnd-$taskStart)))
$statusItem = [pscustomobject]@{Text=''}
$trayExitEvent = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::AutoReset)
function Get-Running { return $script:taskRunning }
try {
    for ($taskIndex=0; $taskIndex -lt 1000; $taskIndex++) {
        $script:taskRunning = ($taskIndex % 2 -eq 0)
        & $taskTick.GetScriptBlock()
        $taskExpected = if ($script:taskRunning) { $runningIcon } else { $stoppedIcon }
        if (-not [object]::ReferenceEquals($notify.Icon, $taskExpected)) { throw 'Icon was recreated instead of reused' }
    }
    'PASS: 1000 status changes reuse two icons; tray syntax valid'
} finally {
    $notify.Dispose()
    $runningIcon.Dispose()
    $stoppedIcon.Dispose()
    $trayExitEvent.Dispose()
}
