$ErrorActionPreference = 'Stop'
$deploymentRoot = Split-Path $PSScriptRoot
$source = Get-Content -LiteralPath (Join-Path $deploymentRoot 'maintenance\ui-operation.ps1') -Raw -Encoding UTF8
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Worker syntax invalid' }
$helper = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-ServiceScript'}, $true)
if (-not $helper) { throw 'Service-script wait helper missing' }
. ([scriptblock]::Create($helper.Extent.Text))
$wakeSource = Get-Content -LiteralPath (Join-Path $deploymentRoot 'maintenance\scheduled-wake\wake_bot.ps1') -Raw -Encoding UTF8
$wakeAst = [Management.Automation.Language.Parser]::ParseInput($wakeSource, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Wake script syntax invalid' }
$wakeHelper = $wakeAst.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-Step'}, $true)
if (-not $wakeHelper) { throw 'Wake wait helper missing' }
. ([scriptblock]::Create($wakeHelper.Extent.Text))
$powerShell = Join-Path $PSHOME 'powershell.exe' 
$fixtureBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$root = Join-Path $fixtureBase ('whale service wait ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$started = Get-Date
$backgroundFile = Join-Path $root 'dummy-background.ps1'
$pidFile = Join-Path $root 'background.pid'
try {
    Set-Content -LiteralPath $backgroundFile -Value 'Start-Sleep -Seconds 8' -Encoding UTF8
    $fixture = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('JEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICdTdG9wJwokZHVtbXkgPSBKb2luLVBhdGggJFBTU2NyaXB0Um9vdCAnZHVtbXktYmFja2dyb3VuZC5wczEnCiRwcm9jZXNzID0gU3RhcnQtUHJvY2VzcyAtRmlsZVBhdGggKEpvaW4tUGF0aCAkUFNIT01FICdwb3dlcnNoZWxsLmV4ZScpIC1Bcmd1bWVudExpc3QgQCgnLU5vUHJvZmlsZScsJy1FeGVjdXRpb25Qb2xpY3knLCdCeXBhc3MnLCctV2luZG93U3R5bGUnLCdIaWRkZW4nLCctRmlsZScsKCciJyArICRkdW1teSArICciJykpIC1XaW5kb3dTdHlsZSBIaWRkZW4gLVJlZGlyZWN0U3RhbmRhcmRPdXRwdXQgKEpvaW4tUGF0aCAkUFNTY3JpcHRSb290ICdiYWNrZ3JvdW5kLm91dCcpIC1SZWRpcmVjdFN0YW5kYXJkRXJyb3IgKEpvaW4tUGF0aCAkUFNTY3JpcHRSb290ICdiYWNrZ3JvdW5kLmVycicpIC1QYXNzVGhydQpTZXQtQ29udGVudCAtTGl0ZXJhbFBhdGggKEpvaW4tUGF0aCAkUFNTY3JpcHRSb290ICdiYWNrZ3JvdW5kLnBpZCcpIC1WYWx1ZSAkcHJvY2Vzcy5JZCAtRW5jb2RpbmcgQVNDSUkKZXhpdCA3Cg=='))
    Set-Content -LiteralPath (Join-Path $root 'start.ps1') -Value $fixture -Encoding UTF8
    foreach ($helperName in @('Invoke-ServiceScript', 'Invoke-Step')) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $code = & $helperName 'start.ps1'
    $watch.Stop()
    if ($code -ne 7) { throw ('Parent exit code lost: ' + $code) }
    if ($watch.ElapsedMilliseconds -ge 4000) { throw ('Helper waited for background descendant: ' + $watch.ElapsedMilliseconds + ' ms') }
    if (-not (Test-Path -LiteralPath $pidFile)) { throw 'Dummy background process did not start' }
    $dummyPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
    $dummy = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $dummyPid)
    if (-not $dummy -or $dummy.Name -ne 'powershell.exe' -or $dummy.CommandLine.IndexOf($backgroundFile, [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Background child already exited or identity mismatched' }
    Write-Output ('PASS: ' + $helperName + ' returned exit 7 in ' + $watch.ElapsedMilliseconds + ' ms while harmless 8-second child was still running; no service action executed')
    if ($dummy.CreationDate -lt $started.AddSeconds(-1)) { throw 'Unexpected dummy creation time' }
    Stop-Process -Id $dummyPid -Force
    Wait-Process -Id $dummyPid -Timeout 3 -ErrorAction SilentlyContinue
    }
} finally {
    if (Test-Path -LiteralPath $pidFile) {
        $dummyPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
        $dummy = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $dummyPid) -ErrorAction SilentlyContinue
        if ($dummy -and $dummy.Name -eq 'powershell.exe' -and $dummy.CommandLine -and $dummy.CommandLine.IndexOf($backgroundFile, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $dummy.CreationDate -ge $started.AddSeconds(-1)) {
            Stop-Process -Id $dummyPid -Force -ErrorAction SilentlyContinue
            Wait-Process -Id $dummyPid -Timeout 3 -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path -LiteralPath $root) {
        $resolved = (Resolve-Path -LiteralPath $root).Path
        if (-not $resolved.StartsWith($fixtureBase, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($resolved) -notlike 'whale service wait *') { throw 'Unexpected fixture cleanup path' }
        Get-ChildItem -LiteralPath $resolved -File | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
        Remove-Item -LiteralPath $resolved
    }
}
