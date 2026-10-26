param([switch]$Test)
# 定时唤醒后的自检：等网络就绪 -> 检查服务端口 -> 检查 QQ 在线 -> 必要时重启 -> 保持白天不休眠
# 位置：<部署目录>\maintenance\scheduled-wake\wake_bot.ps1
$ErrorActionPreference = 'Stop'
# 脚本在 maintenance\scheduled-wake\ 下，项目根目录是上两级
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$logFile = Join-Path $root 'logs\wake.log'

function Write-WakeLog($msg) {
    try {
        $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
        Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    } catch {}
}

function Test-Port($port) {
    $c = [Net.Sockets.TcpClient]::new()
    try {
        $c.Connect('127.0.0.1', $port)
        return $true
    } catch {
        return $false
    } finally {
        $c.Dispose()
    }
}

function Invoke-Step($scriptName, [string[]]$ExtraArguments = @()) {
    $ps = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path $ps)) { $ps = 'powershell.exe' }
    $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"' + (Join-Path $root $scriptName) + '"')) + $ExtraArguments
    $proc = Start-Process -FilePath $ps -ArgumentList $argList -WindowStyle Hidden -PassThru
    try { $proc.WaitForExit(); return $proc.ExitCode } finally { $proc.Dispose() }
}

Write-WakeLog '唤醒任务触发'
Start-Sleep -Seconds 25

if (-not ((Test-Port 6185) -and (Test-Port 6099))) {
    Write-WakeLog '服务未运行，开始启动'
    $code = Invoke-Step 'launcher.ps1' @('-Quiet')
    Write-WakeLog ('启动结束 exit=' + $code)
} else {
    $online = $false
    try {
        . (Join-Path $root 'qq-login.ps1')
        $state = Get-WhaleQQLoginState -Root $root
        $online = [bool]($state.isLogin -and $state.coreReady)
    } catch {
        $online = $false
    }

    if ($online) {
        Write-WakeLog '唤醒后 QQ 在线，无需重启'
    } else {
        Write-WakeLog '唤醒后 QQ 尚未在线，尝试恢复登录'
        $code = Invoke-Step 'launcher.ps1' @('-Quiet')
        Write-WakeLog ('恢复登录结束 exit=' + $code)
    }
}

try {
    . (Join-Path $root 'qq-login.ps1')
    $finalState = Get-WhaleQQLoginState -Root $root
    if ($finalState.isLogin -and $finalState.coreReady) { Write-WakeLog '最终检查：QQ 已在线' }
    else { Write-WakeLog '最终检查：QQ 尚未在线，可能需要手机验证，请检查登录页' }
} catch { Write-WakeLog ('最终检查失败：' + $_.Exception.Message) }

# 白天保持系统不休眠（显示器可以关），默认 14 小时
if (-not $Test) {
    $keep = Join-Path $PSScriptRoot 'keep_awake.ps1'
    if (Test-Path $keep) {
        Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',$keep) -WindowStyle Hidden
        Write-WakeLog '已启动白天保持唤醒'
    }
}
