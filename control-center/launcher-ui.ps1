param([switch]$Tray)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$taskRoot = $PSScriptRoot
. (Join-Path $taskRoot '_lib.ps1')
$deploy=Get-JingyuConfig
$taskCreated = $false
$taskMutex = [Threading.Mutex]::new($true,'Local\WhaleUnifiedLauncher',[ref]$taskCreated)
$taskShowEvent = [Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::AutoReset,'Local\WhaleUnifiedShow')
if (-not $taskCreated) { [void]$taskShowEvent.Set(); $taskShowEvent.Dispose(); $taskMutex.Dispose(); exit }
$taskLock = Join-Path $taskRoot 'runtime/tray.lock'
Set-Content -LiteralPath $taskLock -Value $PID -Encoding UTF8
$script:worker = $null; $script:exiting = $false; $script:exitReady = $false
$script:lastRefresh = [datetime]::MinValue
$script:buttons = @()
$script:cards=@{}
$script:lastState=$null
$script:statusError=$false
$script:stateAt=[datetime]::UtcNow
$script:nextAction=$null
$taskForm = [Windows.Forms.Form]::new()
$taskForm.Text = '小鲸鱼 · 机器人启动器'
$taskForm.ClientSize = [Drawing.Size]::new(720,680)
$taskForm.StartPosition = 'CenterScreen'
$taskForm.FormBorderStyle = 'FixedSingle'
$taskForm.MaximizeBox = $false
$taskForm.BackColor = [Drawing.Color]::FromArgb(244,247,251)
$taskForm.Font = [Drawing.Font]::new('Microsoft YaHei UI',10)
$taskForm.Icon = [Drawing.Icon]::new((Join-Path $taskRoot 'assets/whale.ico'))
function Add-Label($parent,$text,$x,$y,$w,$h,$bold=$false) {
    $label = [Windows.Forms.Label]::new(); $label.Text=$text
    $label.SetBounds($x,$y,$w,$h)
    if ($bold) { $label.Font=[Drawing.Font]::new('Microsoft YaHei UI',13,[Drawing.FontStyle]::Bold) }
    $parent.Controls.Add($label); return $label
}
function Add-Button($parent,$text,$x,$y,$w,$action) {
    $button=[Windows.Forms.Button]::new(); $button.Text=$text; $button.SetBounds($x,$y,$w,36)
    $button.FlatStyle='Flat'; $button.BackColor=[Drawing.Color]::White
    $button.Tag=$action; $button.Add_Click({ Begin-Action ([string]$this.Tag) })
    $parent.Controls.Add($button); $script:buttons += $button; return $button
}
[void](Add-Label $taskForm '小鲸鱼 · 控制中心' 24 18 620 36 $true)
$taskCore=Add-Label $taskForm '正在检查公共服务…' 25 58 660 25
$tabs=[Windows.Forms.TabControl]::new();$tabs.SetBounds(20,92,680,475);$taskForm.Controls.Add($tabs)
$pages=@{}
foreach($name in @('总览','任务与定时','启动设置','运行记录')){
    $page=[Windows.Forms.TabPage]::new($name);$page.BackColor=$taskForm.BackColor;$tabs.TabPages.Add($page);$pages[$name]=$page
}
$overview=$pages['总览']
$script:retries=@{official=0;personal=0};$script:lastRetry=[datetime]::MinValue
$script:previousLights=@{}
$script:exitPending=$false
function New-List($parent,$columns,$y,$height){
    $list=[Windows.Forms.ListView]::new();$list.SetBounds(14,$y,644,$height);$list.View='Details';$list.FullRowSelect=$true;$list.HideSelection=$false
    foreach($col in $columns){[void]$list.Columns.Add($col[0],$col[1])};$parent.Controls.Add($list);return $list
}
$taskList=New-List $pages['任务与定时'] @(@('机器人',100),@('阶段',300),@('耗时',110)) 12 160
[void](Add-Label $pages['任务与定时'] '定时任务 · 选择后可暂停或恢复' 14 182 630 25)
$jobList=New-List $pages['任务与定时'] @(@('任务',220),@('状态',70),@('下次执行',185),@('上次执行',145)) 214 170
$pause=[Windows.Forms.Button]::new();$pause.Text='暂停所选';$pause.SetBounds(14,395,110,34);$pause.Add_Click({Invoke-Job 'job-pause'});$pages['任务与定时'].Controls.Add($pause)
$resume=[Windows.Forms.Button]::new();$resume.Text='恢复所选';$resume.SetBounds(136,395,110,34);$resume.Add_Click({Invoke-Job 'job-resume'});$pages['任务与定时'].Controls.Add($resume)
function Invoke-Job($action){if($jobList.SelectedItems.Count -eq 1){$script:selectedJob=[string]$jobList.SelectedItems[0].Tag;Begin-Action $action}}
$historyList=New-List $pages['运行记录'] @(@('时间',125),@('操作',150),@('结果',350)) 12 350
$logOpen=[Windows.Forms.Button]::new();$logOpen.Text='打开详细日志';$logOpen.SetBounds(14,380,150,34);$logOpen.Add_Click({Start-Process explorer.exe (Join-Path $taskRoot 'logs')});$pages['运行记录'].Controls.Add($logOpen)
$settingsPath=Join-Path $taskRoot 'runtime/launcher-settings.json'
$settings=Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$checks=@{};$row=20
foreach($pair in @(@('boot','登录 Windows 后启动控制中心'),@('official','自动启动官方机器人'),@('personal','自动启动自己的 QQ 机器人'),@('tray','自动启动时只显示托盘'),@('reconnect','连接异常时自动重连（每次间隔 60 秒，最多 3 次）'))){
    $check=[Windows.Forms.CheckBox]::new();$check.Text=$pair[1];$check.SetBounds(22,$row,620,32);$check.Checked=[bool]$settings.($pair[0]);$pages['启动设置'].Controls.Add($check);$checks[$pair[0]]=$check;$row+=46
}
[void](Add-Label $pages['启动设置'] '退出时关闭全部机器人；下次自动启动仍按这里的选择。' 22 270 620 52)
$savePrefs=[Windows.Forms.Button]::new();$savePrefs.Text='保存设置';$savePrefs.SetBounds(22,340,120,36)
$savePrefs.Add_Click({
    try{
        $prefs=@{};foreach($key in $checks.Keys){$prefs[$key]=$checks[$key].Checked}
        $startup=[Environment]::GetFolderPath('Startup');$link=Join-Path $startup '小鲸鱼开机自启.lnk'
        if($prefs.boot){$shell=New-Object -ComObject WScript.Shell;$shortcut=$shell.CreateShortcut($link);$shortcut.TargetPath=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe';$shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+(Join-Path $taskRoot 'launcher.ps1')+'" -Quiet';$shortcut.WorkingDirectory=$taskRoot;$shortcut.Save()}
        elseif(Test-Path -LiteralPath $link){Move-Item -LiteralPath $link -Destination (Join-Path $taskRoot 'runtime/startup-shortcut.backup.lnk') -Force}
        $temp=$settingsPath+'.tmp';$prefs | ConvertTo-Json | Set-Content -LiteralPath $temp -Encoding UTF8;Move-Item -LiteralPath $temp -Destination $settingsPath -Force
        $taskStatus.Text='启动设置已保存'
    }catch{$taskStatus.Text='保存失败：'+$_.Exception.Message}
});$pages['启动设置'].Controls.Add($savePrefs)
[void](Add-Label $overview '当前任务' 18 255 630 28 $true)
$taskSummary=Add-Label $overview '暂无任务' 18 292 630 48
[void](Add-Label $overview '最近动态' 18 350 630 28 $true)
$recent=Add-Label $overview '暂无操作记录' 18 387 630 48
function Update-Details {
    $state=$script:lastState
    $taskCore.Text=if($state.core){'公共服务正常'}else{'公共服务未启动'}
    $taskList.BeginUpdate();$taskList.Items.Clear()
    foreach($row in $state.tasks){
        $end=if($row.finished){[double]$row.finished}else{[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
        $seconds=[int]($end-[double]$row.started);$phase=[string]$row.phase
        if(-not $row.finished -and $seconds -gt 180){$phase+=' · 等待较久，请检查日志'}
        $item=[Windows.Forms.ListViewItem]::new($(if($row.kind -eq 'official'){'官方机器人'}else{'自己的 QQ'}));[void]$item.SubItems.Add($phase);[void]$item.SubItems.Add([string]$seconds+' 秒');[void]$taskList.Items.Add($item)
    };$taskList.EndUpdate()
    $selected=if($jobList.SelectedItems.Count){$jobList.SelectedItems[0].Tag}else{''}
    $jobList.BeginUpdate();$jobList.Items.Clear()
    foreach($job in $state.jobs){$item=[Windows.Forms.ListViewItem]::new([string]$job.name);$item.ToolTipText=[string]$job.note;$jobList.ShowItemToolTips=$true;$item.Tag=if($job.job_id){$job.job_id}else{$job.id};[void]$item.SubItems.Add($(if($job.enabled){'已开启'}else{'已暂停'}));foreach($field in @('next_run_time','last_run_at')){$text='—';if($job.$field){try{$text=([datetimeoffset]::Parse($job.$field)).LocalDateTime.ToString('MM-dd HH:mm')}catch{$text=[string]$job.$field}};[void]$item.SubItems.Add($text)};[void]$jobList.Items.Add($item);if($item.Tag -eq $selected){$item.Selected=$true}}
    $jobList.EndUpdate();$historyList.Items.Clear()
    foreach($entry in $state.history){$item=[Windows.Forms.ListViewItem]::new([string]$entry.time);$actionName=([string]$entry.action).Replace('official','官方机器人').Replace('personal','自己的 QQ').Replace('-restart','重启').Replace('-start','启动').Replace('all-stop','全部关闭').Replace('-stop','关闭').Replace('job-pause','暂停定时').Replace('job-resume','恢复定时');[void]$item.SubItems.Add($actionName);[void]$item.SubItems.Add([string]$entry.detail);[void]$historyList.Items.Add($item)}
    $taskSummary.Text=if(-not $state.monitor_fresh){'任务状态暂时无法确认'}else{$active=@($state.tasks | Where-Object {-not $_.finished});if($active.Count){(@($active | Select-Object -First 2 | ForEach-Object {$(if($_.kind -eq 'official'){'官方'}else{'自己的 QQ'})+' · '+$_.phase}) -join [Environment]::NewLine)}else{'当前空闲'}}
    $recent.Text=if(-not $state.history){'暂无操作记录'}else{(@($state.history | Select-Object -First 2 | ForEach-Object {$_.time+'  '+$_.detail}) -join [Environment]::NewLine)}
}

function New-Card($kind,$title,$subtitle,$x) {
    $panel=[Windows.Forms.Panel]::new();$panel.SetBounds($x,20,310,224);$panel.BackColor=[Drawing.Color]::White
    $overview.Controls.Add($panel)
    [void](Add-Label $panel $title 18 14 268 32 $true)
    [void](Add-Label $panel $subtitle 18 49 268 24)
    $lamp=[Windows.Forms.Panel]::new();$lamp.SetBounds(18,86,18,18);$lamp.Tag='yellow'
    $lamp.Add_Paint({param($sender,$e)
        $e.Graphics.SmoothingMode=[Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $color=switch([string]$sender.Tag){'green'{[Drawing.Color]::FromArgb(33,158,93)}'red'{[Drawing.Color]::FromArgb(214,69,69)}default{[Drawing.Color]::FromArgb(226,161,34)}}
        $brush=[Drawing.SolidBrush]::new($color);$e.Graphics.FillEllipse($brush,1,1,15,15);$brush.Dispose()
    });$panel.Controls.Add($lamp)
    $status=Add-Label $panel '读取状态中…' 45 82 242 29
    $detail=Add-Label $panel '—' 18 111 270 42
    [void](Add-Button $panel '启动' 18 153 82 ($kind+'-start'))
    [void](Add-Button $panel '关闭' 110 153 82 ($kind+'-stop'))
    [void](Add-Button $panel '重启' 202 153 82 ($kind+'-restart'))
    $cancel=[Windows.Forms.Button]::new();$cancel.Text='停止启动';$cancel.SetBounds(18,194,265,26);$cancel.Tag=$kind+'-stop';$cancel.Visible=$false
    $cancel.Add_Click({$script:nextAction=[string]$this.Tag;$taskStatus.Text='已请求停止，将在当前启动步骤结束后关闭连接'});$panel.Controls.Add($cancel)
    $script:cards[$kind]=@{Cancel=$cancel;Lamp=$lamp;Status=$status;Detail=$detail}
}
New-Card 'official' '官方机器人' 'QQ 官方连接' 14
New-Card 'personal' '自己的 QQ 机器人' 'NapCat · 独立登录连接' 342
function Paint-Cards {
    foreach($kind in @('official','personal')){
        $card=$script:cards[$kind];$data=if($script:lastState){$script:lastState.$kind}else{$null}
        $busy=$script:worker -and $script:worker.Action -ne 'status' -and ($script:worker.Action.StartsWith($kind+'-') -or $script:worker.Action -eq 'all-stop')
        if($busy){
            $elapsed=[int]([datetime]::UtcNow-$script:worker.Started).TotalSeconds
            $card.Lamp.Tag='yellow';$card.Status.Text='正在执行 · '+$elapsed+' 秒'
            $card.Detail.Text=switch -Regex ($script:worker.Action){'restart$'{'正在重新建立连接'}'start$'{'正在启动，请稍候'}default{'正在关闭，请稍候'}}
        } elseif($script:statusError){
            $card.Lamp.Tag='yellow';$card.Status.Text='状态未确认';$card.Detail.Text='最后确认：'+$script:stateAt.ToLocalTime().ToString('HH:mm:ss')+'，请刷新或查看日志'
        } elseif($data){
            $card.Lamp.Tag=[string]$data.light
            $active=@($script:lastState.tasks | Where-Object {$_.kind -eq $kind -and -not $_.finished})
            $card.Status.Text=if($data.light -eq 'green' -and $active.Count){$card.Lamp.Tag='yellow';'正在处理 · '+$active.Count+' 个任务'}elseif($data.light -eq 'green'){'已就绪'}elseif($data.light -eq 'red'){'未启动'}else{'等待连接或登录'}
            $card.Detail.Text=if($data.light -eq 'green'){$seconds=[int]$data.running_seconds+[int]([datetime]::UtcNow-$script:stateAt).TotalSeconds;[string]$data.text+[Environment]::NewLine+'已连接 '+[timespan]::FromSeconds($seconds).ToString('hh\:mm\:ss')}else{[string]$data.text+$(if($data.enabled -and $data.light -eq 'yellow'){[Environment]::NewLine+'已等待 '+[string]$data.waiting_seconds+' 秒'}else{''})}
        }
        $card.Cancel.Visible=[bool]($busy -and $script:worker.Action -match '(start|restart)$');$card.Lamp.Invalidate()
    }
    foreach($button in $script:buttons){
        $tag=[string]$button.Tag
        if($script:worker -and $script:worker.Action -ne 'status'){$button.Enabled=$false;continue}
        if($tag -match '^(official|personal)-(start|stop|restart)$' -and $script:lastState){
            $data=$script:lastState.($matches[1]);$button.Enabled=if($matches[2] -eq 'start'){-not $data.enabled}else{[bool]$data.enabled}
        }else{$button.Enabled=$true}
    }
}

[void](Add-Label $taskForm '最小化或关窗口收进托盘；退出启动器会关闭全部机器人。' 25 575 670 25)
$taskStatus=Add-Label $taskForm '就绪' 25 648 670 30
$taskWeb=[Windows.Forms.Button]::new();$taskWeb.Text='管理面板';$taskWeb.SetBounds(25,610,96,34);$taskWeb.Add_Click({Start-Process ('http://127.0.0.1:'+$deploy.dashboard_port)});$taskForm.Controls.Add($taskWeb)
$taskLogin=[Windows.Forms.Button]::new();$taskLogin.Text='QQ 登录';$taskLogin.SetBounds(131,610,96,34);$taskLogin.Add_Click({Start-Process ('http://127.0.0.1:'+$deploy.napcat_port)});$taskForm.Controls.Add($taskLogin)
$taskLogs=[Windows.Forms.Button]::new();$taskLogs.Text='查看日志';$taskLogs.SetBounds(237,610,96,34);$taskLogs.Add_Click({Start-Process explorer.exe (Join-Path $taskRoot 'logs')});$taskForm.Controls.Add($taskLogs)
[void](Add-Button $taskForm '刷新' 343 610 72 'status')
[void](Add-Button $taskForm '全部关闭' 425 610 105 'all-stop')
$taskExit=[Windows.Forms.Button]::new();$taskExit.Text='退出启动器';$taskExit.SetBounds(540,610,114,36);$taskExit.Add_Click({Request-Exit});$taskForm.Controls.Add($taskExit)
$taskNotify=[Windows.Forms.NotifyIcon]::new();$taskNotify.Icon=$taskForm.Icon;$taskNotify.Text='小鲸鱼 · 启动器';$taskNotify.Visible=$true
$taskMenu=[Windows.Forms.ContextMenuStrip]::new()
$taskOpen=$taskMenu.Items.Add('打开启动器');$taskOpen.Add_Click({Show-Window})
foreach ($entry in @(@('启动官方机器人','official-start'),@('关闭官方机器人','official-stop'),@('重启官方机器人','official-restart'),@('启动自己的 QQ','personal-start'),@('关闭自己的 QQ','personal-stop'),@('重启自己的 QQ','personal-restart'),@('全部关闭','all-stop'))) {
    $item=$taskMenu.Items.Add($entry[0]);$item.Tag=$entry[1];$item.Add_Click({Begin-Action ([string]$this.Tag)})
}
$taskTrayExit=$taskMenu.Items.Add('退出并关闭全部');$taskTrayExit.Add_Click({Request-Exit})
$taskNotify.ContextMenuStrip=$taskMenu;$taskNotify.Add_DoubleClick({Show-Window})
function Show-Window { $taskForm.Show();$taskForm.WindowState='Normal';$taskForm.Activate() }
function Request-Exit {
    if ($script:worker -and $script:worker.Action -ne 'status') { $script:exitPending=$true;$taskStatus.Text='当前操作结束后，将关闭全部机器人并退出。';Show-Window;return }
    $script:exiting=$true;Begin-Action 'all-stop'
}
function Begin-Action([string]$action) {
    if ($script:worker) { if($script:worker.Action -eq 'status' -and $action -ne 'status'){$script:nextAction=$action};return }
    $path=Join-Path $taskRoot ('runtime/launcher-'+[guid]::NewGuid().ToString('N')+'.json')
    try {
        $extraArgs=@();if($action -like 'job-*'){$extraArgs=@('--job-id',$script:selectedJob)}
        $process=Start-Process -FilePath (Resolve-JingyuPath $deploy.python) -ArgumentList (@(('"'+(Join-Path $taskRoot 'launcher-control.py')+'"'),$action)+$extraArgs+@('--result',('"'+$path+'"'))) -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru
        $script:worker=@{Process=$process;Path=$path;Action=$action;Started=[datetime]::UtcNow}
        if ($action -ne 'status') { $taskStatus.Text='正在执行，请稍候…';foreach($b in $script:buttons){$b.Enabled=$false} }
    } catch { $taskStatus.Text='未能启动操作：'+$_.Exception.Message;$script:exiting=$false }
}
$taskForm.Add_Resize({if($taskForm.WindowState -eq 'Minimized'){$taskForm.Hide()}})
$taskForm.Add_FormClosing({param($sender,$e) if(-not $script:exitReady){$e.Cancel=$true;$taskForm.Hide()}})
$taskTimer=[Windows.Forms.Timer]::new();$taskTimer.Interval=500
$taskTimer.Add_Tick({
    if($taskShowEvent.WaitOne(0)){Show-Window}
    Paint-Cards
    if($script:worker){
        $p=$script:worker.Process;$p.Refresh()
        if($p.HasExited){
            $action=$script:worker.Action
            try {
                $result=Get-Content -LiteralPath $script:worker.Path -Raw -Encoding UTF8 | ConvertFrom-Json
                if(-not $result.ok){throw [string]$result.error}
                $script:statusError=$false;$script:lastState=$result.state;$script:stateAt=[datetime]::UtcNow;Paint-Cards;Update-Details
                $tip='小鲸鱼 · 官方：'+$result.state.official.text+' / QQ：'+$result.state.personal.text;$taskNotify.Text=$tip.Substring(0,[Math]::Min(63,$tip.Length))
                if($action -ne 'status'){$taskStatus.Text='操作已完成；连接状态以卡片为准'}
                foreach($kind in @('official','personal')){
                    $light=[string]$result.state.$kind.light
                    if($script:previousLights.ContainsKey($kind) -and $script:previousLights[$kind] -ne $light -and $light -eq 'red' -and $result.state.$kind.enabled){$taskNotify.ShowBalloonTip(4000,'小鲸鱼','机器人连接异常，请打开控制中心检查',[Windows.Forms.ToolTipIcon]::Warning)}
                    $script:previousLights[$kind]=$light
                    if($light -eq 'green'){$script:retries[$kind]=0}
                }
                if($script:exiting -and $action -eq 'all-stop'){$script:exitReady=$true;$taskForm.Close();[Windows.Forms.Application]::Exit()}
            } catch {$script:statusError=$true;$taskStatus.Text=$_.Exception.Message;$script:exiting=$false;if($action -ne 'status'){Show-Window}}
            Remove-Item -LiteralPath $script:worker.Path -Force -ErrorAction SilentlyContinue
            $p.Dispose();$script:worker=$null;$script:lastRefresh=[datetime]::UtcNow
            Paint-Cards
            if($script:exitPending){$script:exitPending=$false;Request-Exit}
            elseif($script:nextAction){$queued=$script:nextAction;$script:nextAction=$null;Begin-Action $queued}
        } elseif($script:worker.Action -ne 'status'){$taskStatus.Text='操作进行中 · '+[int]([datetime]::UtcNow-$script:worker.Started).TotalSeconds+' 秒（退出将等待收尾）'}
    } elseif(([datetime]::UtcNow-$script:lastRefresh).TotalSeconds -ge 5){
        $retry=$null
        if($checks['reconnect'].Checked -and -not $script:statusError -and ([datetime]::UtcNow-$script:lastRetry).TotalSeconds -ge 60){
            foreach($kind in @('official','personal')){if($script:lastState.$kind.enabled -and $script:lastState.$kind.text -eq '连接异常' -and $script:retries[$kind] -lt 3){$retry=$kind;break}}
        }
        if($retry){$script:retries[$retry]++;$script:lastRetry=[datetime]::UtcNow;$taskStatus.Text='自动重连 '+$script:retries[$retry]+'/3';Begin-Action ($retry+'-restart')}else{Begin-Action 'status'}
    }
})
$positionPath=Join-Path $taskRoot 'runtime/launcher-window.json'
if(Test-Path -LiteralPath $positionPath){try{$position=Get-Content $positionPath -Raw | ConvertFrom-Json;$point=[Drawing.Point]::new($position.x,$position.y);if([Windows.Forms.Screen]::AllScreens | Where-Object {$_.WorkingArea.Contains($point)}){$taskForm.StartPosition='Manual';$taskForm.Location=$point}}catch{}}
$taskForm.Add_LocationChanged({if($taskForm.WindowState -eq 'Normal'){@{x=$taskForm.Left;y=$taskForm.Top}|ConvertTo-Json|Set-Content -LiteralPath $positionPath -Encoding UTF8}})
$taskTimer.Start()
if(-not $Tray){$taskForm.Show()}
Begin-Action 'status'
try {[Windows.Forms.Application]::Run()} finally {
    $taskTimer.Stop();$taskTimer.Dispose();$taskNotify.Visible=$false;$taskNotify.Dispose();$taskMenu.Dispose()
    $taskShowEvent.Dispose();$taskMutex.ReleaseMutex();$taskMutex.Dispose()
    Remove-Item -LiteralPath $taskLock -Force -ErrorAction SilentlyContinue
}
