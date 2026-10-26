$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot
. (Join-Path $taskRoot 'qq-login.ps1')
$script:taskCalls=0
function Invoke-RestMethod {
    param($Uri,$Method,$ContentType,$Body,$Headers,$TimeoutSec)
    $script:taskCalls++
    if($Uri -like '*/api/auth/login') { return @{data=@{Credential='test-only'}} }
    if($Headers.Authorization -ne 'Bearer test-only') { throw 'missing credential' }
    if($Uri -like '*/PasswordLogin') {
        $taskPayload=$Body|ConvertFrom-Json
        if($taskPayload.uin -ne '10003'){throw 'wrong bot account'}
        if($taskPayload.passwordMd5 -ne '337761e292109441bad830c3c72b2db9'){throw 'password hashing mismatch'}
        return @{code=0;data=@{needNewDevice=$script:taskNeedsVerification}}
    }
    return @{data=@{isLogin=$script:taskOnline;coreReady=$script:taskOnline;loginPhase='ready';loginError=''}}
}
$script:taskOnline=$true
$taskState=Get-WhaleQQLoginState -Root $taskRoot
if(-not $taskState.isLogin -or -not $taskState.coreReady){throw 'online status lost'}
$script:taskOnline=$false
$taskState=Get-WhaleQQLoginState -Root $taskRoot
if($taskState.isLogin){throw 'offline treated as online'}
if($script:taskCalls -ne 3){throw 'polling must reuse its authentication credential'}
$taskSecure=ConvertTo-SecureString 'test-only-secret' -AsPlainText -Force
$taskCipher=ConvertFrom-SecureString $taskSecure
$taskRestored=ConvertTo-SecureString $taskCipher
if([Net.NetworkCredential]::new('',$taskRestored).Password -ne 'test-only-secret'){throw 'DPAPI roundtrip failed'}
Write-Output 'PASS: authenticated online/offline status and Windows password encryption'

$script:taskNeedsVerification=$false
$taskResult=Invoke-WhaleQQPasswordLogin -Root $taskRoot -Password $taskSecure
if(-not $taskResult.Success){throw 'password success not recognized'}
$script:taskNeedsVerification=$true
$taskResult=Invoke-WhaleQQPasswordLogin -Root $taskRoot -Password $taskSecure
if($taskResult.Success -or -not $taskResult.VerificationRequired){throw 'verification treated as logged in'}
Write-Output 'PASS: password login request and verification-required handling'
