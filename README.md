# 小鲸鱼 · QQ 聊天机器人

> 一个跑在自己 Windows 电脑上的 QQ 机器人：AstrBot 做对话与调度，NapCat 接入 QQ，22 个自写插件负责群管理、表情、桌面操作和日常运维。

<p align="center">
  <img src="assets/whale.png" alt="小鲸鱼" width="96">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/Code_License-Personal_Use_NonCommercial-orange.svg" alt="Personal Use Non-Commercial"></a>
  <a href="LICENSE-CC-BY-NC-SA-4.0.md"><img src="https://img.shields.io/badge/Docs_%26_Persona-CC_BY--NC--SA_4.0-lightgrey.svg" alt="CC BY-NC-SA 4.0"></a>
  <img src="https://img.shields.io/badge/Platform-Windows_10%2F11-0078D4.svg" alt="Windows">
  <img src="https://img.shields.io/badge/AstrBot-4.x-6A5ACD.svg" alt="AstrBot 4.x">
</p>

> [!WARNING]
> 这是作者**自用**的机器人工程，不是开箱即用的产品。它依赖第三方 QQ 客户端 NapCat，**可能违反腾讯 QQ 用户协议并导致账号被限制**，请只用自己的小号和自建群测试。
> 项目与腾讯、DeepSeek、AstrBot 官方均无隶属关系。

> 维护者：**ashishi05**（小鲸鱼项目贡献者）· 个人非官方项目

---

## 目录

- [这是什么](#这是什么)
- [功能](#功能)
- [运行架构](#运行架构)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [配置项](#配置项)
- [插件清单](#插件清单)
- [人设](#人设)
- [安全与隐私](#安全与隐私)
- [已知限制与风险](#已知限制与风险)
- [运维与排错](#运维与排错)
- [许可](#许可)
- [免责声明](#免责声明)

---

## 这是什么

小鲸鱼是一个「住在家里的 QQ 助手」：你用自己的小号登录，她在私聊里陪你聊天、查资料、处理文件，在群里按规则接话，还能替管理员管广告、发发表情包、定时提醒。

工程本身由三层组成：

| 层 | 谁来做 | 本仓库是否包含 |
|---|---|---|
| QQ 接入 | [NapCat](https://github.com/NapNeko/NapCatQQ)（第三方 QQ 客户端） | ❌ 需自行下载 |
| 对话引擎 / 插件宿主 | [AstrBot 4.x](https://github.com/AstrBotDevs/AstrBot)（AGPL-3.0） | ❌ 需自行安装 |
| 启动器、托盘、插件、人设 | 本项目 | ✅ |

本仓库只公开**作者自己写的部分**，方便想搭同类机器人的人参考，不附带模型权重、聊天数据库或任何账号凭据。

## 功能

**私聊**
- 接 DeepSeek / 本地 Ollama 等模型聊天，支持联网搜索、文件与表格处理
- 两个自用 QQ 号共享同一段私聊上下文（`owner_session`）
- 回复自动分条、去 AI 味、截断提示
- 管理员可用 `local_desktop` 让机器人截图、操作本机窗口（高风险，见[安全](#安全与隐私)）

**群聊**
- 默认必须 @ 才会接话；三分钟连续对话窗口 + 群友回复限流
- 管理员 / 普通群友权限分离，普通群友只能用联网搜索
- 5 秒内连续消息合并、空 @ 读取上下文、群图片缓存
- 进群自动同步群库、机器人账号识别

**表情**
- 表情收藏、标签选图、按 `[[tag:标签]]` 自动配图
- 静态 WebP 自动转 PNG，适配 QQ 群

**管理员工具**
- 消息撤回、拍一拍、定时提醒、睡眠模式
- 校园群广告风控：识别群号 / 进群链接 / 二维码，撤回 + 禁言 + 私聊通知

**运维**
- 一键启动 / 关闭 / 托盘常驻 / 开机静默自启
- QQ 密码本机 DPAPI 加密，支持密码登录兜底
- 定时唤醒（睡眠 → 到点开机、恢复机器人）

## 运行架构

```
桌面快捷方式 / 启动机器人.cmd
        │
        ▼
   launcher.ps1 ──启动──▶ start.ps1
        │                    ├─ AstrBot (main.py, 端口 6185)
        │                    └─ NapCat  (node index.js, 端口 6099)
        │                              │ QQ 反向 WS 6199
        ▼                              ▼
   tray.ps1（托盘）          AstrBot WebUI 管理页
        │
        └─ stop.ps1 / stopper.ps1 统一收尾
```

- 所有脚本用 `$PSScriptRoot` 定位仓库根目录，**换盘、换目录都不用改代码**
- QQ 号、目录、端口统一放在根目录 `config.json`（由 `config.example.json` 复制而来，已被 `.gitignore` 忽略）

## 目录结构

```
小鲸鱼/
├─ launcher.ps1 / stopper.ps1     # 一键启动 / 关闭（弹提示）
├─ start.ps1 / stop.ps1           # 真正的服务启停
├─ tray.ps1                       # 托盘图标（状态、重启、管理页）
├─ qq-login.ps1                   # NapCat 登录状态与密码登录
├─ qq-password-setup.ps1          # 本机加密保存 QQ 密码
├─ _lib.ps1                       # 配置读取与路径解析
├─ autostart.vbs                  # 开机静默启动
├─ config.example.json            # 配置模板（复制成 config.json）
├─ plugins/                       # 22 个自写 AstrBot 插件
├─ persona/                       # 鲸鱼娘人设示例与改法
├─ maintenance/                   # 定时唤醒、表情导出等维护工具
├─ docs/                          # 运维手册
├─ assets/                        # 托盘图标
├─ AstrBot/                       # 自行安装（不入库）
├─ NapCat/                        # 自行下载（不入库）
├─ runtime/                       # 运行时凭据与进程记录（不入库）
└─ logs/                          # 日志（不入库）
```

## 快速开始

### 1. 准备

- Windows 10/11 64 位，PowerShell 5.1
- 一个**专用于机器人**的 QQ 小号（别用主号）
- 可选：NVIDIA 显卡不是必须的，用云端模型即可

### 2. 装 AstrBot

推荐直接用 [AstrBot 官方发行版](https://github.com/AstrBotDevs/AstrBot/releases)（自带 dashboard 前端），解压后把目录改名为 `AstrBot` 放在本仓库根目录。

从源码安装也可以：

```powershell
git clone https://github.com/AstrBotDevs/AstrBot.git
cd AstrBot
uv venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> AstrBot 采用 AGPL-3.0，使用和修改请遵守它的许可与 EULA。

### 3. 装 NapCat

从 [NapCatQQ Releases](https://github.com/NapNeko/NapCatQQ/releases) 下载 Windows Shell 版，解压到本仓库根目录并改名 `NapCat`（确保存在 `NapCat\node.exe` 与 `NapCat\index.js`）。

本项目**不附带也不分发** NapCat。它的许可与腾讯 QQ 用户协议请自行确认。

### 4. 配置

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

至少改这三项：`qq`（机器人 QQ）、`python`（AstrBot 的 python 路径）、`astrbot_dir` / `napcat_dir`（如果目录名不同）。

### 5. 放插件

```powershell
# 把 plugins 下的目录复制到 AstrBot 的数据目录
Copy-Item plugins\* "$PWD\AstrBot\data\plugins\" -Recurse -Force
```

插件里的 `10001` / `10002` 是**管理员 QQ 占位号**，换成你自己的（见[插件清单](#插件清单)）。

可选但推荐装 [meme_manager](https://github.com/anka-afk/astrbot_plugin_meme_manager)（MIT），`meme_tag` / `meme_admin` 依赖它的表情数据。

### 6. 启动与登录

双击 `启动机器人.cmd`（或桌面快捷方式）。首次启动会：

1. 拉起 AstrBot（6185）和 NapCat（6099）
2. 自动打开 NapCat 登录页，用手机 QQ 扫码
3. 登录成功后，AstrBot 管理页在 `http://127.0.0.1:6185`

想免扫码：运行 `设置QQ自动登录.cmd`，密码用 DPAPI 加密存在本机 `runtime\qq-password.dpapi`，**不会上传**。

开机自启：把 `autostart.vbs` 的快捷方式放进 `shell:startup`。

## 配置项

`config.json`（全部可选，缺省值见 `_lib.ps1`）：

| 键 | 默认 | 说明 |
|---|---|---|
| `qq` | `10003` | 机器人 QQ 号 |
| `astrbot_dir` | `AstrBot` | AstrBot 目录，相对仓库根或绝对路径 |
| `napcat_dir` | `NapCat` | NapCat 目录 |
| `python` | `AstrBot\.venv\Scripts\python.exe` | 启动 AstrBot 的 Python |
| `deepseek_key_file` | `runtime\deepseek-key.dpapi` | 可选，DPAPI 加密的 API Key |
| `dashboard_port` | `6185` | AstrBot 端口 |
| `napcat_port` | `6099` | NapCat WebUI 端口 |
| `qq_port` | `6199` | QQ 反向 WebSocket 端口 |

## 插件清单

| 插件 | 作用 |
|---|---|
| `owner_session` | 两个自用号共享私聊上下文 |
| `msg_merge` | 5 秒内连续消息合并成一条 |
| `empty_at` | 空 @ 时读取最近聊天记录当上下文 |
| `at_filter` | 只 @ 别人时机器人不插嘴 |
| `img_cache` | 群图片先缓存，被 @ 时再交给模型 |
| `reply_style` | 回复不加 @，群聊用引用回复 |
| `chat_delivery` | 按 `[split]` 分条发送、清理引用组件 |
| `deai_clean` | 删掉模型爱说的空壳套话 |
| `token_guard` | 回复被截断时提示「继续」 |
| `group_roles` | 管理员 / 普通群友权限区分 |
| `group_window` | 群聊三分钟连续对话窗口 + 限流 |
| `group_autojoin` | 管理员说「更新群库」同步群列表 |
| `group_bot_note` | 识别机器人账号，注入「只点评别多聊」 |
| `ad_guard` | 指定群的广告风控（群号 / 链接 / 二维码） |
| `sleep_mode` | 「没你事儿了」进入睡眠，@ 才醒 |
| `meme_manager` | *第三方*（MIT），表情包管理 |
| `meme_admin` | 管理员批量收录、整理表情 |
| `meme_tag` | 按标签发图、自动配图 |
| `function_menu` | 菜单与功能说明 |
| `local_desktop` | Windows 桌面截图与操作（仅管理员私聊） |
| `msg_recall` | 撤回指定消息 |
| `poke_tool` | 拍一拍 |
| `img_debug` | 调试消息组件结构（默认别开） |

> **替换占位号**：`10001` / `10002` 是管理员 QQ，`200000001` / `200000002` 是群号，`10003` / `10004` 是机器人号。全局搜索替换即可：
>
> ```powershell
> Get-ChildItem plugins -Recurse -Filter *.py | Select-String "10001|10002"
> ```

## 人设

`persona/人设示例.md` 是一份可直接粘进 AstrBot 人格设置的「鲸鱼娘」人设：私聊亲近、群聊克制、管理员与群友分级。

- 想换成别的人设：直接在 WebUI 里改
- 想改称呼：全文替换「老大」即可，具体见 [persona/README.md](persona/README.md)
- 人设里的人名、号码都是占位符，**别把真实的群号和管理员号提交到仓库**

> 鲸鱼娘是 DeepSeek 社区的二创形象，本项目属于非官方同人工程；相关名称与商标归各自权利人所有。

## 安全与隐私

- 🔒 `config.json`、`runtime/`、`logs/`、`data_v4.db`、`管理入口.txt` 已在 `.gitignore` 中，**提交前仍请 `git status` 确认**
- 🔒 QQ 密码只以 DPAPI 加密形式存本机，换电脑/换用户无法解密
- 🔒 机器人不向作者或第三方服务器上传聊天记录；但模型提供商、NapCat、插件可能有各自网络行为，请自行核查
- ⚠️ `local_desktop` 会让管理员通过 QQ 控制本机桌面。只在自己的电脑、自己的号上用；不要把管理权限给了别人
- ⚠️ 仓库里不要出现真实 QQ 号、群号、聊天截图、API Key

## 已知限制与风险

1. **QQ 协议风险**：NapCat 基于 NTQQ 客户端，属于非官方接入。腾讯可能随时限制或封禁账号，后果自负
2. **不是即插即用**：需要自己装 AstrBot、NapCat，配置模型和人格
3. **Windows 专用**：脚本是 PowerShell + WinForms，托盘和桌面操作只在 Windows 可用
4. **无自动化测试**：本仓库不带测试套件，行为以实际运行结果为准
5. **AGPL 约束**：AstrBot 是 AGPL-3.0，如果你把它和本项目一起再分发，需要满足 AGPL 的源码开放要求

## 运维与排错

启动失败先看 `logs\launcher.log`、`logs\astrbot.err.log`、`logs\napcat.err.log`。

- 6185/6099 端口被占：`Get-NetTCPConnection -LocalPort 6185,6099`
- QQ 掉线：托盘 → 打开管理页 → 扫码 / 密码登录
- 插件没生效：确认放在 `AstrBot\data\plugins\<插件名>\main.py`，且 AstrBot 已重载
- 详细步骤见 [docs/运维手册.md](docs/运维手册.md)

## 许可

本项目采用分层许可：

- **代码**（`*.ps1`、`*.vbs`、`plugins/*/main.py`、`maintenance/*.py`）：[个人使用许可（非商业）](LICENSE)
- **文档、人设与提示词**（`*.md`、`persona/`）：[CC BY-NC-SA 4.0](LICENSE-CC-BY-NC-SA-4.0.md)
- **图标**：随项目以个人使用许可（非商业）提供；如涉及第三方素材，以 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 为准
- **不包含**：AstrBot（AGPL-3.0）、NapCat、模型权重、第三方插件

## 免责声明

- 本项目是个人自用的非官方工程，与腾讯、DeepSeek、AstrBot、NapCat 官方**无隶属或合作关系**
- 使用第三方 QQ 客户端可能违反平台协议，账号风险由使用者承担
- 机器人产生的内容、群管理操作（撤回、禁言）及由此引发的后果，由部署者负责
- 请遵守所在地法律与平台规则；禁止用于骚扰、诈骗、侵犯隐私、传播违法内容或规避平台审核
- 软件按「现状」提供，不提供任何明示或暗示担保

---

*Powered by 白米饭 🍚 × 鲸鱼娘 🐳 × 社区之爱 💙*