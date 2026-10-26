# 第三方组件与权利说明

本仓库**不包含**下列组件的代码或二进制，只在文档中说明如何获取。它们各自的许可、条款与风险由使用者自行确认。

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
- 关系：可选依赖。`meme_tag` / `meme_admin` 读取它的表情数据；本仓库不分发该插件及其表情资源。

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
