$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')
$cfg = Get-JingyuConfig
Import-Module -Name (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
# 兼容修复：清理大小写重复的代理环境变量（NO_PROXY/no_proxy 等）
# 否则 PowerShell 5.1 的 Start-Process 会抛 "Item has already been added" 导致启动失败
try {
    $taskSeen = @{}
    foreach ($taskLine in @(& cmd.exe /c set 2>$null)) {
        if ($taskLine -match '^([^=]+)=(.*)$') {
            $taskKey = $matches[1].ToLowerInvariant()
            if ($taskSeen.ContainsKey($taskKey)) { [Environment]::SetEnvironmentVariable($matches[1], $null) }
            else { $taskSeen[$taskKey] = 1 }
        }
    }
} catch { }
$taskRoot = $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# 目录按需创建，首次部署也能直接跑
foreach ($taskDir in @('logs', 'runtime')) {
    $taskPath = Join-Path $taskRoot $taskDir
    if (-not (Test-Path -LiteralPath $taskPath)) { New-Item -ItemType Directory -Path $taskPath -Force | Out-Null }
}

# DEEPSEEK_API_KEY：有本机加密文件就解密注入，没有就沿用环境变量 / AstrBot 自己的配置
$taskKeyFile = Resolve-JingyuPath $cfg.deepseek_key_file
if ($taskKeyFile -and (Test-Path -LiteralPath $taskKeyFile)) {
    try {
        $taskSecure = (Get-Content -LiteralPath $taskKeyFile -Raw).Trim() | ConvertTo-SecureString
        $env:DEEPSEEK_API_KEY = [Net.NetworkCredential]::new('', $taskSecure).Password
    } catch {
        Write-Warning 'DEEPSEEK_API_KEY 解密失败，改用环境变量或 AstrBot 配置里的密钥。'
    }
}

$taskProcesses = @{}
$taskPidFile = "$taskRoot/runtime/started-processes.json"
if (Test-Path -LiteralPath $taskPidFile) {
    $taskPrevious = Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json
    foreach ($taskProperty in $taskPrevious.PSObject.Properties) { $taskProcesses[$taskProperty.Name] = $taskProperty.Value }
}
$taskAstrbotDir = Resolve-JingyuPath $cfg.astrbot_dir
$taskNapcatDir = Resolve-JingyuPath $cfg.napcat_dir
$taskPython = Resolve-JingyuPath $cfg.python
$taskQq = [string]$cfg.qq
foreach ($taskExe in @($taskPython, (Join-Path $taskNapcatDir 'node.exe'))) {
    if (-not (Test-Path -LiteralPath $taskExe)) {
        throw ("找不到可执行文件：$taskExe`n请检查 config.json 里的 python / napcat_dir 配置。")
    }
}
foreach ($taskService in @(
    @{Name='astrbot'; Port=[int]$cfg.dashboard_port; File=$taskPython; Args=@('main.py'); Dir=$taskAstrbotDir},
    @{Name='napcat'; Port=[int]$cfg.napcat_port; File=(Join-Path $taskNapcatDir 'node.exe'); Args=@('index.js','-q',$taskQq); Dir=$taskNapcatDir}
)) {
    $taskSocket = [Net.Sockets.TcpClient]::new()
    try { $taskSocket.Connect('127.0.0.1', $taskService.Port); $taskRunning = $true } catch { $taskRunning = $false } finally { $taskSocket.Dispose() }
    if (-not $taskRunning -and $taskProcesses.ContainsKey($taskService.Name)) {
        $taskRecorded = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProcesses[$taskService.Name])" -ErrorAction SilentlyContinue
        if ($taskRecorded -and $taskRecorded.ExecutablePath -and
            [IO.Path]::GetFullPath($taskRecorded.ExecutablePath) -eq [IO.Path]::GetFullPath($taskService.File)) {
            $taskRunning = $true
        }
    }
    if ($taskRunning) { continue }
    # 只将解密密码传给 NapCat 子进程，启动后立即清除父进程中的副本。
    try {
        if ($taskService.Name -eq 'napcat' -and (Test-Path -LiteralPath "$taskRoot/runtime/qq-password.dpapi")) {
            $taskQqSecure = (Get-Content -LiteralPath "$taskRoot/runtime/qq-password.dpapi" -Raw).Trim() | ConvertTo-SecureString
            $env:NAPCAT_QUICK_PASSWORD = [Net.NetworkCredential]::new('', $taskQqSecure).Password
        }
    $taskProcess = Start-Process -FilePath $taskService.File -ArgumentList $taskService.Args -WorkingDirectory $taskService.Dir -WindowStyle Hidden -RedirectStandardOutput "$taskRoot/logs/$($taskService.Name).out.log" -RedirectStandardError "$taskRoot/logs/$($taskService.Name).err.log" -PassThru
    } finally {
        if ($taskService.Name -eq 'napcat') { Remove-Item Env:NAPCAT_QUICK_PASSWORD -ErrorAction SilentlyContinue }
    }
    $taskProcesses[$taskService.Name] = $taskProcess.Id
}
$taskProcesses | ConvertTo-Json | Set-Content -LiteralPath "$taskRoot/runtime/started-processes.json" -Encoding UTF8
Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
$taskUiReady = $false
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    $taskSocket = [Net.Sockets.TcpClient]::new()
    try {
        $taskSocket.Connect('127.0.0.1', [int]$cfg.napcat_port)
        $taskUiReady = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    } finally {
        $taskSocket.Dispose()
    }
}
if (-not $taskUiReady) { throw 'QQ 管理页面未能启动，请查看 logs/napcat.err.log。' }
. (Join-Path $taskRoot 'qq-login.ps1')
$taskQqOnline = $false
for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
    try {
        $taskLogin = Get-WhaleQQLoginState -Root $taskRoot
        if ($taskLogin.isLogin -and $taskLogin.coreReady) { $taskQqOnline = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $taskQqOnline) {
    $taskPasswordFile = Join-Path $taskRoot 'runtime/qq-password.dpapi'
    if (-not (Test-Path -LiteralPath $taskPasswordFile)) {
        # 首次设置直接弹出本机凭据窗口，不再要求用户另找设置入口。
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $taskRoot 'qq-password-setup.ps1') -NoPause *> $null
    }
    if (Test-Path -LiteralPath $taskPasswordFile) {
        try {
            $taskSecurePassword = (Get-Content -LiteralPath $taskPasswordFile -Raw).Trim() | ConvertTo-SecureString
            $taskPasswordResult = Invoke-WhaleQQPasswordLogin -Root $taskRoot -Password $taskSecurePassword
            if ($taskPasswordResult.Message -match '安全风险|使用受限|恢复账号') {
                Add-Content -LiteralPath "$taskRoot/logs/launcher.log" -Value ("[{0}] QQ 返回账号安全限制，需要在手机 QQ 恢复账号" -f (Get-Date -Format 'HH:mm:ss')) -Encoding UTF8
                Write-Output "QQ 账号使用受限，请先在手机 QQ 登录 $taskQq 并按提示恢复。"
                exit 2
            }
            if ($taskPasswordResult.Success) {
                for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
                    $taskLogin = Get-WhaleQQLoginState -Root $taskRoot
                    if ($taskLogin.isLogin -and $taskLogin.coreReady) { $taskQqOnline = $true; break }
                    Start-Sleep -Milliseconds 500
                }
            }
            Add-Content -LiteralPath "$taskRoot/logs/launcher.log" -Value ("[{0}] 密码登录已尝试：在线={1}，需要安全验证={2}" -f (Get-Date -Format 'HH:mm:ss'), $taskQqOnline, $taskPasswordResult.VerificationRequired) -Encoding UTF8
        } catch {
            Add-Content -LiteralPath "$taskRoot/logs/launcher.log" -Value ("[{0}] 密码登录未完成，请在 QQ 管理页检查验证或密码" -f (Get-Date -Format 'HH:mm:ss')) -Encoding UTF8
        } finally { $taskSecurePassword = $null }
    }
}
if ($taskQqOnline) {
    Write-Output 'QQ 已登录，服务已启动。'
} else {
    # 需要人工验证时始终显示入口，不能让旧的“已打开”标记挡住登录页。
    $taskWebUiPath = Join-Path $taskNapcatDir 'napcat/config/webui.json'
    $taskWebUi = Get-Content -LiteralPath $taskWebUiPath -Raw | ConvertFrom-Json
    $taskLoginUrl = 'http://127.0.0.1:' + [int]$cfg.napcat_port + '/webui?token=' + [Uri]::EscapeDataString($taskWebUi.token)
    Start-Process -FilePath $taskLoginUrl
    Write-Output '服务已启动，QQ 尚未完成登录；请在打开的页面完成验证。'
}

# ===== 托盘图标：与机器人同生命周期（start 拉起，stop -KeepTray 保留）=====
$trayScript = Join-Path $taskRoot 'tray.ps1'
$trayLock = Join-Path $taskRoot 'runtime/tray.lock'
$trayAlive = $false
if (Test-Path -LiteralPath $trayLock) {
    $trayPidRaw = (Get-Content -LiteralPath $trayLock -Raw -ErrorAction SilentlyContinue)
    if ($trayPidRaw) {
        $trayPidText = $trayPidRaw.Trim()
        if ($trayPidText -match '^\d+$') {
            if (Get-Process -Id ([int]$trayPidText) -ErrorAction SilentlyContinue) { $trayAlive = $true }
        }
    }
}
if (-not $trayAlive -and (Test-Path -LiteralPath $trayScript)) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File', ('"' + $trayScript + '"')) -WindowStyle Hidden
}
