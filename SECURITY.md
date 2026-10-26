# 安全策略

## 不要提交的内容

以下文件和目录已在 `.gitignore` 中，但提交前仍请用 `git status` 人工确认：

| 路径 | 原因 |
|---|---|
| `config.json` | 含机器人 QQ 号、本机路径 |
| `runtime/` | 含 DPAPI 加密的 QQ 密码、API Key、进程记录 |
| `logs/` | 日志可能含群号、QQ 号、聊天片段 |
| `管理入口.txt` | 管理页账号密码 |
| `AstrBot/data/data_v4.db*` | 聊天记录数据库 |
| `NapCat/`、`AstrBot/` | 第三方程序与登录态 |
| `*.dpapi` | 本机加密凭据 |

## 密钥处理

- QQ 密码：`设置QQ自动登录.cmd` 用 Windows DPAPI 加密保存，绑定当前 Windows 用户，换机无法解密
- 模型 API Key：优先放环境变量或 AstrBot 的 provider 配置；不要写进插件代码、Commit、Issue 或截图
- 如果你误提交了密钥：立刻在对应平台吊销/轮换，再用 `git filter-repo` 清理历史；仅删除文件不够

## 高风险功能

`plugins/local_desktop` 允许管理员通过 QQ 私聊让机器人截图、移动鼠标、操作窗口。

- 只在自己独占的电脑上启用
- 不要把它暴露给非管理员
- 不要把带有管理权限的机器人拉进不受信任的群
- 发现异常操作立即 `停止机器人.cmd` 并检查 `logs/`

## 漏洞报告

请通过 GitHub Issue 或仓库主页公开的联系方式私下报告，不要直接公开 PoC。收到后会尽快确认。

本项目是个人自用工程，不提供安全响应 SLA。
