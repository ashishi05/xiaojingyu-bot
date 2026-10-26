' 小鲸鱼 QQ 机器人 —— 开机静默启动
' 用脚本自身所在目录定位 launcher.ps1，换盘、换目录都不用改这里
Dim shell, fso, here
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
WScript.Sleep 20000
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\launcher.ps1"" -Quiet", 0, False
Set shell = Nothing
Set fso = Nothing
