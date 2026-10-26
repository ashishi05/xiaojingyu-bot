param([switch]$KeepTray)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')
$cfg = Get-JingyuConfig
$taskPorts = @([int]$cfg.dashboard_port, [int]$cfg.qq_port, [int]$cfg.napcat_port)
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
$taskPidFile = Join-Path $taskRoot 'runtime/started-processes.json'
$taskSnapshot = @(Get-CimInstance Win32_Process)
$taskTargets = New-Object 'System.Collections.Generic.HashSet[int]'
function Test-WhaleProcess($Process) {
    return ($Process -and $Process.ExecutablePath -and $Process.ExecutablePath.StartsWith($taskRoot, [StringComparison]::OrdinalIgnoreCase))
}
if (Test-Path -LiteralPath $taskPidFile) {
    $taskRecorded = Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json
    foreach ($taskProperty in $taskRecorded.PSObject.Properties) {
        $taskMatch = $taskSnapshot | Where-Object { $_.ProcessId -eq [int]$taskProperty.Value }
        if (Test-WhaleProcess $taskMatch) { [void]$taskTargets.Add([int]$taskMatch.ProcessId) }
    }
}
foreach ($taskConnection in @(Get-NetTCPConnection -LocalPort $taskPorts -State Listen -ErrorAction SilentlyContinue)) {
    $taskMatch = $taskSnapshot | Where-Object { $_.ProcessId -eq $taskConnection.OwningProcess }
    if (Test-WhaleProcess $taskMatch) { [void]$taskTargets.Add([int]$taskMatch.ProcessId) }
}
do {
    $taskAdded = $false
    foreach ($taskChild in $taskSnapshot) {
        if ($taskTargets.Contains([int]$taskChild.ParentProcessId) -and (Test-WhaleProcess $taskChild)) {
            if ($taskTargets.Add([int]$taskChild.ProcessId)) { $taskAdded = $true }
        }
    }
} while ($taskAdded)
foreach ($taskId in $taskTargets) { Stop-Process -Id $taskId -Force -ErrorAction SilentlyContinue }
for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
    $taskRemaining = @(Get-NetTCPConnection -LocalPort $taskPorts -State Listen -ErrorAction SilentlyContinue)
    if ($taskRemaining.Count -eq 0) { break }
    Start-Sleep -Milliseconds 200
}
if ($taskRemaining.Count -gt 0) { throw '服务端口仍被占用；已避免关闭未经确认的进程，请查看日志。' }
if (-not $KeepTray) {
    try {
        $taskExitEvent = [Threading.EventWaitHandle]::OpenExisting('Local\WhaleTrayExit')
        try { [void]$taskExitEvent.Set() } finally { $taskExitEvent.Dispose() }
    } catch [Threading.WaitHandleCannotBeOpenedException] { }
}
Write-Output '机器人后台已停止。'
