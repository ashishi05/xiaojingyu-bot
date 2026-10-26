$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks
$root = Split-Path $PSScriptRoot
$workerPath = Join-Path $root 'maintenance\ui-operation.ps1'
$source = Get-Content -LiteralPath $workerPath -Raw -Encoding UTF8
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Worker syntax invalid' }
$before = Export-ScheduledTask -TaskName '小鲸鱼-定时唤醒'
$fixtureDir = Join-Path $env:TEMP ('whale-ui-operation-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureDir | Out-Null
$created = New-Object 'Collections.Generic.List[string]'
$cases = @(
    @{Name='start-online'; Action='Start'; Online=$true; Ports=$true; StartExit=0; StopExit=0; AfterStartOnline=$true; AfterStartPorts=$true; Level='success'; Exit=0; Trace=@()},
    @{Name='start-success'; Action='Start'; Online=$false; Ports=$false; StartExit=0; StopExit=0; AfterStartOnline=$true; AfterStartPorts=$true; Level='success'; Exit=0; Trace=@('start')},
    @{Name='start-waits-qq'; Action='Start'; Online=$false; Ports=$false; StartExit=0; StopExit=0; AfterStartOnline=$false; AfterStartPorts=$true; Level='warning'; Exit=2; Trace=@('start')},
    @{Name='start-failed'; Action='Start'; Online=$false; Ports=$false; StartExit=1; StopExit=0; AfterStartOnline=$false; AfterStartPorts=$false; Level='error'; Exit=1; Trace=@('start')},
    @{Name='restart-sequence'; Action='Restart'; Online=$true; Ports=$true; StartExit=0; StopExit=0; AfterStartOnline=$true; AfterStartPorts=$true; Level='success'; Exit=0; Trace=@('stop','start')},
    @{Name='restart-stop-failed'; Action='Restart'; Online=$true; Ports=$true; StartExit=0; StopExit=1; AfterStartOnline=$true; AfterStartPorts=$true; Level='error'; Exit=1; Trace=@('stop')},
    @{Name='stop-success'; Action='Stop'; Online=$true; Ports=$true; StartExit=0; StopExit=0; AfterStartOnline=$false; AfterStartPorts=$false; Level='success'; Exit=0; Trace=@('stop')},
    @{Name='stop-failed'; Action='Stop'; Online=$true; Ports=$true; StartExit=0; StopExit=1; AfterStartOnline=$false; AfterStartPorts=$false; Level='error'; Exit=1; Trace=@('stop')},
    @{Name='stop-listener-survived'; Action='Stop'; Online=$true; Ports=$true; StartExit=0; StopExit=0; SurviveStop=$true; Level='error'; Exit=1; Trace=@('stop')},
    @{Name='save-wake'; Action='SaveWake'; Online=$false; Ports=$false; SavedWake=$true; Level='success'; Exit=0; Trace=@('save')},
    @{Name='save-verification-failed'; Action='SaveWake'; Online=$false; Ports=$false; SavedWake=$false; Level='error'; Exit=1; Trace=@('save')},
    @{Name='disable-wake'; Action='SaveWake'; Disable=$true; Online=$false; Ports=$false; SavedWake=$true; Level='success'; Exit=0; Trace=@('disable')},
    @{Name='invalid-result-path'; Action='Start'; Online=$true; Ports=$true; Level='error'; Exit=1; InvalidPath=$true; Trace=@()}
)
try {
    foreach ($case in $cases) {
        $fixture = Join-Path $fixtureDir ($case.Name + '.ps1')
        $tracePath = Join-Path $fixtureDir ($case.Name + '.trace.json')
        $resultPath = Join-Path $root ('runtime\ui-' + [guid]::NewGuid().ToString('N') + '.json')
        if ($case.InvalidPath) { $resultPath = Join-Path $fixtureDir 'ui-invalid.json' }
        $created.Add($fixture); $created.Add($tracePath); $created.Add($resultPath); $created.Add($resultPath + ".progress.json")
        $scenarioJson = ($case | ConvertTo-Json -Compress).Replace("'", "''")
        $mock = @'
Import-Module ScheduledTasks
$script:scenario = '__SCENARIO__' | ConvertFrom-Json
$script:trace = New-Object 'Collections.Generic.List[string]'
$script:online = [bool]$script:scenario.Online
$script:ports = [bool]$script:scenario.Ports
$script:taskState = 'Ready'
$script:taskWake = $true
function Mock-OperationShell {
    $parts = @($args)
    $fileIndex = [Array]::IndexOf($parts, '-File')
    $target = [string]$parts[$fileIndex + 1]
    if ($target -like '*stop.ps1') {
        $script:trace.Add('stop')
        $global:LASTEXITCODE = [int]$script:scenario.StopExit
        if ($global:LASTEXITCODE -eq 0 -and -not $script:scenario.SurviveStop) { $script:ports = $false; $script:online = $false }
    } elseif ($target -like '*start.ps1') {
        $script:trace.Add('start')
        $global:LASTEXITCODE = [int]$script:scenario.StartExit
        $script:online = [bool]$script:scenario.AfterStartOnline
        $script:ports = [bool]$script:scenario.AfterStartPorts
    } else { throw 'Unexpected child command' }
}
function Mock-SaveSchedule {
    param($Date, $Time, [switch]$Daily)
    $script:trace.Add('save')
    $script:taskState = 'Ready'
    $script:taskWake = [bool]$script:scenario.SavedWake
}
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    return [pscustomobject]@{State=$script:taskState; Settings=[pscustomobject]@{WakeToRun=$script:taskWake}}
}
function Get-ScheduledTaskInfo {
    param($TaskName)
    return [pscustomobject]@{NextRunTime=[datetime]'2026-10-27T10:00:00'}
}
function Disable-ScheduledTask {
    param($TaskName)
    $script:trace.Add('disable')
    $script:taskState = 'Disabled'
}
'@
        $mock = $mock.Replace('__SCENARIO__', $scenarioJson)
        $fixtureSource = $source
        foreach ($name in @('Test-Port','Get-Online')) {
            $node = $ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $true)
            $replacement = if ($name -eq 'Test-Port') { 'function Test-Port($port) { return $script:ports }' } else { 'function Get-Online { return $script:online }' }
            $fixtureSource = $fixtureSource.Replace($node.Extent.Text, $replacement)
        }
        $serviceNode = $ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-ServiceScript'}, $true)
        if (-not $serviceNode) { throw 'Updated Invoke-ServiceScript function is required; refusing to launch real service commands' }
        $serviceMock = @'
function Invoke-ServiceScript($Name, [switch]$KeepTray) {
    $tokens = @('-File', (Join-Path $root $Name))
    if ($KeepTray) { $tokens += '-KeepTray' }
    Mock-OperationShell @tokens
    return $global:LASTEXITCODE
}
'@
        $fixtureSource = $fixtureSource.Replace($serviceNode.Extent.Text, $serviceMock)
        $fixtureSource = $fixtureSource.Replace('$root = Split-Path $PSScriptRoot', ("`$root = '" + $root.Replace("'", "''") + "'"))
        $fixtureSource = $fixtureSource.Replace("`$powerShell = Join-Path `$PSHOME 'powershell.exe'", ("`$powerShell = 'Mock-OperationShell'`r`n" + $mock))
        $fixtureSource = $fixtureSource.Replace("`$setup = Join-Path `$root 'maintenance\scheduled-wake\setup-task.ps1'", "`$setup = 'Mock-SaveSchedule'")
        $traceWriter = "[IO.File]::WriteAllText('" + $tracePath.Replace("'", "''") + "', (ConvertTo-Json -InputObject @(`$script:trace) -Compress))`r`n"
        $fixtureSource = $fixtureSource.Replace('$result | ConvertTo-Json -Compress', ($traceWriter + '$result | ConvertTo-Json -Compress'))
        Set-Content -LiteralPath $fixture -Value $fixtureSource -Encoding UTF8
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName = Join-Path $PSHOME 'powershell.exe'
        $psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $fixture + '" -Action ' + $case.Action + ' -ResultPath "' + $resultPath + '" -Date 2026-10-27 -Time 10:00'
        if ($case.Disable) { $psi.Arguments += ' -Disable' }
        $psi.WorkingDirectory = $root
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $process = [Diagnostics.Process]::Start($psi)
        try {
            if (-not $process.WaitForExit(10000)) { $process.Kill(); throw ('Fixture timed out: ' + $case.Name) }
            $stdout = $process.StandardOutput.ReadToEnd()
            $stderr = $process.StandardError.ReadToEnd()
            if ($process.ExitCode -ne $case.Exit) { throw ($case.Name + ': unexpected exit ' + $process.ExitCode + '; ' + $stderr + $stdout) }
            if ($case.InvalidPath) {
                if (Test-Path -LiteralPath $resultPath) { throw 'Invalid result path was written' }
                if ($stderr -notlike '*Invalid UI result path*') { throw 'Invalid result path was not rejected' }
                continue
            }
            $result = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($result.level -ne $case.Level) { throw ($case.Name + ': unexpected level ' + $result.level) }
            if ($result.success -ne ($case.Level -eq 'success')) { throw ($case.Name + ': inconsistent success') }
            $trace = Get-Content -LiteralPath $tracePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if (($trace -join ',') -ne ($case.Trace -join ',')) { throw ($case.Name + ': unexpected child actions ' + ($trace -join ',')) }
        } finally { $process.Dispose() }
    }
    $after = Export-ScheduledTask -TaskName '小鲸鱼-定时唤醒'
    if ($before -ne $after) { throw 'Worker tests changed the actual scheduled task' }
    Write-Output ('PASS: ' + $cases.Count + ' operation cases; no live start/stop/browser/task changes')
} finally {
    foreach ($path in $created) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $fixtureDir) { Remove-Item -LiteralPath $fixtureDir -ErrorAction SilentlyContinue }
}
