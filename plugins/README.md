# 插件说明

29 个自写插件依赖 AstrBot 4.x 的 `Star` 接口。原有功能多为单文件插件；七种猜猜杯玩法另带 `metadata.yaml`、题库和共用游戏引擎。

猜猜杯与新版 `function_menu` 共用 `emoji_guess` 引擎，需一起安装或升级。只移除 `emoji_guess` 而保留依赖它的插件会导致导入失败。题库共 296／42／55／71／55／481／70 组，具体规则见各玩法 README。

## 安装

```powershell
# 复制到 AstrBot 数据目录（目录名必须和插件名一致）
Copy-Item plugins\* AstrBot\data\plugins\ -Recurse -Force
```

重启 AstrBot，或在管理页里重载插件。插件在启动时读取自己的常量，改代码后需重载才生效。

## 必须先改的占位号

| 占位符 | 含义 | 出现在 |
|---|---|---|
| `10001` / `10002` | 管理员 QQ | `ad_guard`、`function_menu`、`group_*`、`meme_*`、`msg_recall`、`owner_session`、`poke_tool`、`sleep_mode` |
| `100000001` | 广告管理的目标群 | `ad_guard`、`group_autojoin` |
| `10004` | 其它机器人账号 | `group_bot_note` |

```powershell
# 找出所有需要改的位置
Get-ChildItem plugins -Recurse -Filter *.py | Select-String "10001|10002|100000001|10004"
```

改完统一替换即可。**这些是占位符，不是真实 QQ 号**——公开仓库里请继续保持占位。

## 可选依赖

- `meme_tag` / `meme_admin` 依赖第三方插件 [meme_manager](https://github.com/anka-afk/astrbot_plugin_meme_manager)（MIT）产生的 `plugin_data/meme_manager` 数据
- 没装 `meme_manager` 时，表情相关功能会自动降级（找不到图就跳过），不影响聊天
- 增强戳一戳可单独安装 `astrbot_plugin_pokepro`（GPL v3），不随本仓库分发，见第三方说明
- `local_desktop` 只对 Windows 有效，且仅管理员私聊可用
- `img_debug` 只用于调试，平时别开，会刷日志

## 按用途分组

| 分组 | 插件 |
|---|---|
| 会话与输入 | `owner_session`、`msg_merge`、`empty_at`、`img_cache`、`at_filter` |
| 回复样式 | `chat_delivery`、`deai_clean`、`reply_style`、`token_guard` |
| 群聊 | `group_roles`、`group_window`、`group_autojoin`、`group_bot_note` |
| 广告风控 | `ad_guard`（仅指定群） |
| 表情 | `meme_manager`（第三方）、`meme_admin`、`meme_tag` |
| 猜猜杯 | `emoji_guess`、`country_guess`、`videogame_guess`、`famous_person_guess`、`network_person_guess`、`idiom_guess`、`trivia_guess` |
| 管理与工具 | `local_desktop`、`msg_recall`、`poke_tool`、`function_menu`、`sleep_mode` |

## 改代码的注意事项

- 数据目录统一用 `Path(__file__).resolve().parents[2] / "plugin_data" / "<插件名>"`，不要写死绝对路径
- 插件之间不要互相 import 业务代码；`meme_admin` 是例外，它通过 `sys.path` 复用 `meme_manager`
- 权限判断集中在各插件的 `ADMINS` / `_ALLOWED` 常量，新增管理员记得同步所有插件

## 许可

第三方或改编题库不适用下面的代码许可：成语题库来源与 MIT 许可见 `idiom_guess/licenses/`；冷知识题库的 CC BY-SA 4.0 说明见 `trivia_guess/LICENSE-DATA.md`。

插件代码采用 [个人使用许可（非商业）](../LICENSE)；插件说明文字与提示词采用 [CC BY-NC-SA 4.0](../LICENSE-CC-BY-NC-SA-4.0.md)。
