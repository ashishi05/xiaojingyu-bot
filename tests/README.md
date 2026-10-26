# 测试

这些测试针对**完整部署目录**编写：目录下应有 `AstrBot/`、`maintenance/`，插件位于 `AstrBot/data/plugins/`。仓库本身是源码快照，运行时把 `tests/` 放在部署根目录（与 `AstrBot/` 同级）即可。

- Python：`python tests/test_ad_guard.py`
- PowerShell：`powershell -File tests/test_tray_feedback.ps1`
- 依赖：已安装 AstrBot、可用的 Python 环境；部分 PowerShell 测试需要 Windows 计划任务
- 文件中 QQ 号 / 群号均为占位符（`10001` / `10002` / `10003`、`200000001`…），运行前按自己的部署替换

注意：部分测试会读写计划任务、弹出窗口，建议在测试机或非生产时段运行。