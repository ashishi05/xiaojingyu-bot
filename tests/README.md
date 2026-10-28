# 测试

这些测试针对**完整部署目录**编写：目录下应有 `AstrBot/`、`maintenance/`，插件位于 `AstrBot/data/plugins/`。仓库本身是源码快照，运行时把 `tests/` 放在部署根目录（与 `AstrBot/` 同级）即可。

- Python：`python tests/test_ad_guard.py`
- PowerShell：`powershell -File tests/test_tray_feedback.ps1`
- 依赖：已安装 AstrBot、可用的 Python 环境；部分 PowerShell 测试需要 Windows 计划任务
- 文件中 QQ 号 / 群号均为占位符（`10001` / `10002` / `10003`、`200000001`…），运行前按自己的部署替换

注意：部分测试会读写计划任务、弹出窗口，建议在测试机或非生产时段运行。
## 2026-10-28 新增检查

- `emoji_guess/test_game.py`、`emoji_guess/test_adapter.py`：对局、积分、指令与原生会话隔离。
- `country_guess/`、`videogame_guess/`、`famous_person_guess/`、`network_person_guess/`、`idiom_guess/`：题库与规则回归。
- `test_guess_menu.py`：菜单、玩法启停、继续与结束入口。
- `test_bot_pipeline.py`、`test_desktop_regression.py`：附件、图片缓存、文本清理及模拟桌面边界。

测试应在临时部署目录运行；需要 AstrBot API 时使用自己的已安装环境。游戏测试使用临时数据库和模拟消息，不带真实积分文件。
