$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot
$global:WhaleTestStopped=@()
$global:WhaleTestForeignListener=$false
function Start-Sleep {param($Milliseconds)}
function Get-Content { param($LiteralPath,[switch]$Raw) return '{"astrbot":100,"napcat":200}' }
function Get-CimInstance {
    param($ClassName)
    return @(
        [pscustomobject]@{ProcessId=100;ParentProcessId=1;ExecutablePath=(Join-Path $taskRoot 'AstrBot\.venv\Scripts\python.exe')},
        [pscustomobject]@{ProcessId=101;ParentProcessId=100;ExecutablePath=(Join-Path $taskRoot 'runtime\python\python.exe')},
        [pscustomobject]@{ProcessId=102;ParentProcessId=100;ExecutablePath='C:\Windows\outside.exe'},
        [pscustomobject]@{ProcessId=200;ParentProcessId=1;ExecutablePath='C:\Windows\unrelated.exe'}
    )
}
function Get-NetTCPConnection {
    param($LocalPort,$State)
    if($global:WhaleTestForeignListener){return [pscustomobject]@{OwningProcess=200}}
    if(101 -notin $global:WhaleTestStopped){return [pscustomobject]@{OwningProcess=101}}
}
function Stop-Process {param($Id,[switch]$Force) $global:WhaleTestStopped+= [int]$Id}
& (Join-Path $taskRoot 'stop.ps1') -KeepTray
if(100 -notin $global:WhaleTestStopped -or 101 -notin $global:WhaleTestStopped){throw 'parent or worker survived'}
if(102 -in $global:WhaleTestStopped -or 200 -in $global:WhaleTestStopped){throw 'unrelated process killed'}
$global:WhaleTestStopped=@()
$global:WhaleTestForeignListener=$true
$taskFailed=$false
try { & (Join-Path $taskRoot 'stop.ps1') -KeepTray } catch {$taskFailed=$true}
if(-not $taskFailed){throw 'foreign occupied port reported as stopped'}
if(200 -in $global:WhaleTestStopped){throw 'foreign listener killed'}
Write-Output 'PASS: parent and child shutdown, reused PID protection, foreign port protection'
