param(
    [string]$Time = '10:00',
    [string]$Date = '',
    [switch]$Daily,
    [switch]$Remove,
    [switch]$Status
)
# 小鲸鱼定时唤醒：注册 / 查看 / 删除 Windows 计划任务
# 位置：<部署目录>\maintenance\scheduled-wake\setup-task.ps1
$ErrorActionPreference = 'Stop'
$taskName = '小鲸鱼-定时唤醒'
$wakeScript = Join-Path $PSScriptRoot 'wake_bot.ps1'

if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Output "已删除计划任务：$taskName"
    } else {
        Write-Output "计划任务不存在：$taskName"
    }
    return
}

if ($Status) {
    $t = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $t) { Write-Output "计划任务不存在：$taskName"; return }
    $i = Get-ScheduledTaskInfo -TaskName $taskName
    Write-Output "任务：$taskName"
    Write-Output ("状态：" + $t.State)
    Write-Output ("下次运行：" + $i.NextRunTime)
    Write-Output ("上次运行：" + $i.LastRunTime)
    Write-Output ("上次结果：" + $i.LastTaskResult)
    Write-Output ("唤醒电脑：" + $t.Settings.WakeToRun)
    return
}

if (-not (Test-Path $wakeScript)) { throw "找不到唤醒脚本：$wakeScript" }

$clock = [datetime]::ParseExact($Time, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$timeSpan = $clock.TimeOfDay
if ($Daily) {
    $trigger = New-ScheduledTaskTrigger -Daily -At ((Get-Date).Date.Add($timeSpan))
    $whenText = "每天 " + $Time
} else {
    if ($Date) {
        $when = [datetime]::ParseExact(($Date + ' ' + $Time), 'yyyy-MM-dd HH:mm', $null)
    } else {
        $when = (Get-Date).Date.Add($timeSpan)
        if ($when -le (Get-Date)) { $when = $when.AddDays(1) }
    }
    if ($when -le (Get-Date)) { throw "唤醒时间必须晚于现在" }
    $trigger = New-ScheduledTaskTrigger -Once -At $when
    $whenText = $when.ToString('yyyy-MM-dd HH:mm')
}

$action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $wakeScript + '"')
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description '定时唤醒电脑并检查小鲸鱼 QQ 在线' -Force | Out-Null

Write-Output ("已创建计划任务：" + $taskName)
Write-Output ("触发时间：" + $whenText)
Write-Output "唤醒电脑：是"
Write-Output ("执行脚本：" + $wakeScript)
Write-Output "提示：电脑必须是「睡眠」状态才能被唤醒；关机状态 Windows 无法自行开机。"
