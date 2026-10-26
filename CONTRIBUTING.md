# 贡献指南

这是一个个人自用工程，公开出来主要供参考。欢迎 Issue 与 PR，但请先读下面几条。

## 提交前

1. **不要提交任何真实账号、群号、聊天记录、截图、API Key**
2. 跑一遍自检：

   ```powershell
   # PowerShell 语法检查
   Get-ChildItem *.ps1 | ForEach-Object { [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$null, [ref]$null) }
   ```

3. 改插件时确认数据路径用的是 `Path(__file__).resolve().parents[2]`，不要写绝对路径
4. 新增或修改管理员相关逻辑时，把 `10001` / `10002` 占位号保留住

## PR 范围

适合：

- 修 bug、补错误处理
- 提升 Windows 兼容性
- 文档、注释、部署脚本可读性
- 新的通用插件（不含个人数据）

不太适合：

- 大改架构、引入重依赖
- 需要真实 QQ 号才能复现的改动（请先描述复现条件）

## 安全

涉及凭据、桌面控制、权限提升的改动请先开 Issue 说明，不要直接 PR 带权限扩张的代码。

## 许可

提交代码即表示同意以 [个人使用许可（非商业）](LICENSE) 发布；文档与人设的贡献按 [CC BY-NC-SA 4.0](LICENSE-CC-BY-NC-SA-4.0.md) 共享。
