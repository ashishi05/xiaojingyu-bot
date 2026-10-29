# 第三方组件与权利说明

AstrBot、NapCat 与梗百科的程序代码或二进制不随仓库提供；按文档自行安装。表情管理器及拍一拍唤醒插件的源码随仓库提供，并分别适用其原有许可证。`meme_data/` 附带本次整理的表情图片及标签，猜猜杯附带题库；这些数据的来源与许可单独说明。

## AstrBot

- 项目：<https://github.com/AstrBotDevs/AstrBot>
- 许可：**GNU Affero General Public License v3.0（AGPL-3.0）**
- 关系：本项目的插件运行在 AstrBot 上；本仓库不包含 AstrBot 源码。
- 注意：若你把 AstrBot 与本项目一起再分发，或对外提供修改后的网络服务，需遵守 AGPL-3.0 的源码开放义务；AstrBot 另有自己的 EULA，请一并阅读。

## NapCat

- 项目：<https://github.com/NapNeko/NapCatQQ>
- 关系：QQ 接入客户端，本项目只调用它，不附带、不分发。
- 注意：NapCat 属于非官方 QQ 客户端，使用可能违反腾讯 QQ 用户协议并导致账号受限；其许可与合规性请以项目方说明和当地法律为准。

## meme_manager

- 项目：<https://github.com/anka-afk/astrbot_plugin_meme_manager>
- 作者：anka
- 许可：**MIT**
- 关系：`meme_tag` / `meme_admin` 读取它的表情数据；本仓库包含部署版本的插件源码，许可见 `plugins/meme_manager/LICENSE`。本次附带的表情收藏是独立数据快照，图片并非因插件采用 MIT 就获得 MIT 授权，见 [meme_data/README.md](meme_data/README.md)。

## 模型与 API

- DeepSeek、OpenAI、Gemini、火山引擎等模型服务由各自提供方运营，调用产生的费用、内容责任与数据政策以各自条款为准。
- 本项目不包含任何模型权重。

## astrbot_plugin_memewiki（梗百科）

- 项目：<https://github.com/in1t1a1/astrbot_plugin_memewiki>
- 作者：in1t1a1
- 许可：**MIT**
- 关系：**可选**第三方插件；本仓库不包含其代码、词库数据库（约 16 MB）或图标。
- 说明：`persona/人设示例.md` 的「梗与黑话」规则会调用该插件注册的 `search_meme_wiki` 工具；未安装时按「没有这个工具」处理。
## 名称与商标

- **DeepSeek / 深度求索**：商标归杭州深度求索人工智能基础技术研究有限公司所有。本项目是非官方社区同人工程，不代表官方认可。
- **QQ / 腾讯**：商标归腾讯公司所有。本项目与腾讯无任何隶属或合作关系。
- **鲸鱼娘（Whale-chan）**：源于 DeepSeek 社区网友的集体二创，角色形象的基础设定属于社区共创；具体美术素材的著作权归各原作者。商业使用角色形象需另行取得授权。

## 图标

`assets/whale.ico` 等图标为项目自制/AI 生成素材，随代码以个人使用许可（非商业）提供。如你认为其中包含你的作品，请提 Issue 联系处理。

## 猜猜杯题库

- 成语题库使用 emoji-chengyu 和 THUOCL 的 MIT 数据，来源、筛选与原许可保存在 `plugins/idiom_guess/README.md` 及 `licenses/`。
- 冷知识题库包含 Open Trivia Database 改编及独立编写的中文陈述，题库文本按 CC BY-SA 4.0 共享，详见 `plugins/trivia_guess/LICENSE-DATA.md`；陈述的核对来源保留在数据中。
- 角色、游戏和人物名称归各权利人；题库不代表与相关厂商或人物存在合作关系。

## 专业戳一戳（可选）

- 项目：[Zhalslar/astrbot_plugin_pokepro](https://github.com/Zhalslar/astrbot_plugin_pokepro)。
- 作者：Zhalslar；本机版本 v2.1.1，随插件保存的许可为 GNU GPL v3。
- 本仓库包含基于该插件改造的拍一拍唤醒入口及上游许可证，见 `plugins/astrbot_plugin_pokepro/LICENSE`。该插件采用 GPL-3.0，适用其自身许可。
