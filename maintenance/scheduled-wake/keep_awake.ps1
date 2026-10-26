# 保持系统唤醒：防止唤醒后因为空闲又睡回去（显示器照常可以关）
# 位置：<部署目录>\maintenance\scheduled-wake\keep_awake.ps1
$hours = 14
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$mutex = [Threading.Mutex]::new($false, 'Local\WhaleScheduledKeepAwake')
$ownsMutex = $false
try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) { $mutex.Dispose(); return }
try {
$deadline = (Get-Date).AddHours($hours)
while ((Get-Date) -lt $deadline) {
    [Win32.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null
    Start-Sleep -Seconds 60
}

} finally {
    [Win32.Power]::SetThreadExecutionState([uint32]2147483648) | Out-Null
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
