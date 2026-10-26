param([switch]$NoPause, [string]$Qq)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')
if (-not $Qq) { $Qq = [string](Get-JingyuConfig).qq }
Import-Module -Name (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
try {
    $taskCredential = Get-Credential -UserName $Qq -Message "输入机器人 QQ $Qq 的密码；仅加密保存在当前电脑，不发送到聊天"
    if (-not $taskCredential) { exit 0 }
    if ($taskCredential.UserName -ne $Qq) { throw "这里仅用于机器人 QQ $Qq" }
    if ($taskCredential.Password.Length -eq 0) { throw '密码不能为空' }
    $taskPath = Join-Path $PSScriptRoot 'runtime\qq-password.dpapi'
    $taskCredential.Password | ConvertFrom-SecureString | Set-Content -LiteralPath $taskPath -Encoding UTF8
    Write-Host '已加密保存。下次启动 NapCat 时会在快捷登录失败后尝试密码登录。'
    Write-Host '当前已在线时无需重启；QQ 要求验证时仍需手机确认。'
    Write-Host '如需取消保存，删除 runtime\qq-password.dpapi 即可。'
} catch {
    Write-Host '设置未完成，请重新运行并检查输入。'
    if ($NoPause) { exit 1 }
}
if (-not $NoPause) { Read-Host '按回车关闭窗口' }
