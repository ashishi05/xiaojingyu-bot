# NapCat 登录状态查询与密码登录（端口、目录、QQ 号都来自 config.json）
$script:WhaleQqCredential = $null
if (-not (Get-Command Get-JingyuConfig -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot '_lib.ps1')
}
$script:WhaleCfg = Get-JingyuConfig

function Get-WhaleNapCatDir {
    param([string]$Root = $PSScriptRoot)
    $dir = [string]$script:WhaleCfg.napcat_dir
    if ([IO.Path]::IsPathRooted($dir)) { return $dir }
    return (Join-Path $Root $dir)
}

function Get-WhaleQQLoginState {
    param([string]$Root = $PSScriptRoot)
    $taskPort = [int]$script:WhaleCfg.napcat_port
    if (-not $script:WhaleQqCredential) {
        $taskWebUiPath = Join-Path (Get-WhaleNapCatDir $Root) 'napcat\config\webui.json'
        $taskConfig = Get-Content -LiteralPath $taskWebUiPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $taskSha = [Security.Cryptography.SHA256]::Create()
        try {
            $taskHash = ([BitConverter]::ToString($taskSha.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskConfig.token + '.napcat')))).Replace('-', '').ToLowerInvariant()
        } finally { $taskSha.Dispose() }
        $taskAuth = Invoke-RestMethod -Uri ("http://127.0.0.1:$taskPort/api/auth/login") -Method Post -ContentType 'application/json' -Body (@{hash=$taskHash} | ConvertTo-Json -Compress) -TimeoutSec 2
        if (-not $taskAuth.data.Credential) { throw '无法验证 QQ 登录状态' }
        $script:WhaleQqCredential = $taskAuth.data.Credential
    }
    $taskResponse = Invoke-RestMethod -Uri ("http://127.0.0.1:$taskPort/api/QQLogin/CheckLoginStatus") -Method Post -Headers @{Authorization='Bearer ' + $script:WhaleQqCredential} -ContentType 'application/json' -Body '{}' -TimeoutSec 2
    if (-not $taskResponse.data) { throw 'QQ 登录状态接口返回异常' }
    return $taskResponse.data
}

function Invoke-WhaleQQPasswordLogin {
    param([string]$Root = $PSScriptRoot, [Parameter(Mandatory=$true)][Security.SecureString]$Password)
    $taskPort = [int]$script:WhaleCfg.napcat_port
    $taskState = Get-WhaleQQLoginState -Root $Root
    if ($taskState.isLogin -and $taskState.coreReady) {
        return [pscustomobject]@{Success=$true; VerificationRequired=$false}
    }
    $taskMd5 = [Security.Cryptography.MD5]::Create()
    $taskBytes = $null
    try {
        $taskBytes = [Text.Encoding]::UTF8.GetBytes([Net.NetworkCredential]::new('', $Password).Password)
        $taskPasswordHash = ([BitConverter]::ToString($taskMd5.ComputeHash($taskBytes))).Replace('-', '').ToLowerInvariant()
        $taskBody = @{uin=[string]$script:WhaleCfg.qq; passwordMd5=$taskPasswordHash} | ConvertTo-Json -Compress
        $taskResponse = Invoke-RestMethod -Uri ("http://127.0.0.1:$taskPort/api/QQLogin/PasswordLogin") -Method Post -Headers @{Authorization='Bearer ' + $script:WhaleQqCredential} -ContentType 'application/json' -Body $taskBody -TimeoutSec 20
        $taskVerification = [bool]($taskResponse.data.needCaptcha -or $taskResponse.data.needNewDevice)
        return [pscustomobject]@{Success=($taskResponse.code -eq 0 -and -not $taskVerification); VerificationRequired=$taskVerification; Message=[string]$taskResponse.message; Code=$taskResponse.code}
    } finally {
        if ($taskBytes) { [Array]::Clear($taskBytes, 0, $taskBytes.Length) }
        $taskMd5.Dispose()
        $taskPasswordHash = $null
        $taskBody = $null
    }
}
