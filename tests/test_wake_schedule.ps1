$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$setup = Join-Path $root 'maintenance\scheduled-wake\setup-task.ps1'
foreach ($path in @((Join-Path $root 'tray.ps1')) + @(Get-ChildItem (Join-Path $root 'maintenance\scheduled-wake') -Filter '*.ps1' | Select-Object -ExpandProperty FullName)) {
    $tokens = $null; $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ('Syntax error: ' + $path + ' ' + $errors[0].Message) }
}
Import-Module ScheduledTasks
# Intercept persistence; real trigger construction still runs in Windows PowerShell.
function Register-ScheduledTask {
    param($TaskName, $Action, $Trigger, $Settings, $Principal, $Description, [switch]$Force)
    $global:wakeCaptured = [pscustomobject]@{Name=$TaskName; Action=$Action; Trigger=$Trigger; Settings=$Settings; Principal=$Principal}
}
& $setup -Daily -Time '10:30' | Out-Null
if ($global:wakeCaptured.Trigger.CimClass.CimClassName -ne 'MSFT_TaskDailyTrigger') { throw 'Daily trigger missing' }
if (([datetime]$global:wakeCaptured.Trigger.StartBoundary).ToString('HH:mm') -ne '10:30') { throw 'Daily time changed' }
if (-not $global:wakeCaptured.Settings.WakeToRun) { throw 'Wake flag missing' }
if ($global:wakeCaptured.Principal.LogonType -ne 3) { throw 'Task no longer uses logged-in user session' }
if ($global:wakeCaptured.Action.Arguments -notlike '*wake_bot.ps1*') { throw 'Wrong task entrypoint' }
$tomorrow = (Get-Date).AddDays(1).ToString('yyyy-MM-dd')
& $setup -Date $tomorrow -Time '11:20' | Out-Null
if (([datetime]$global:wakeCaptured.Trigger.StartBoundary).ToString('yyyy-MM-dd HH:mm') -ne ($tomorrow + ' 11:20')) { throw 'One-shot date changed' }
foreach ($invalid in @(@{Date=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd'); Time='10:00'}, @{Time='25:00'})) {
    $rejected = $false
    try { & $setup @invalid | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Invalid or past time accepted' }
}
$keep = Get-Content (Join-Path $root 'maintenance\scheduled-wake\keep_awake.ps1') -Raw
$match = [regex]::Match($keep, 'SetThreadExecutionState\(\[uint32\](\d+)\)')
if (-not $match.Success -or [uint32]$match.Groups[1].Value -ne [uint32]2147483649) { throw 'Invalid native power flags' }
$wake = Get-Content (Join-Path $root 'maintenance\scheduled-wake\wake_bot.ps1') -Raw
if ($wake -match "Invoke-Step 'stop.ps1'") { throw 'Wake path still stops live QQ services' }
'PASS: daily/one-shot wake triggers, invalid dates, native flags and non-destructive reconnect; no task registered'
