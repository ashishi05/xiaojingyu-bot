# 公共工具：部署根目录与配置读取
# 所有入口脚本都 dot-source 本文件，避免各自写死路径。

$script:JingyuRoot = $PSScriptRoot
$script:JingyuConfig = $null

function Get-JingyuConfig {
    if ($script:JingyuConfig) { return $script:JingyuConfig }
    $cfg = [ordered]@{
        qq               = '10003'
        astrbot_dir      = 'AstrBot'
        napcat_dir       = 'NapCat'
        python           = 'AstrBot\.venv\Scripts\python.exe'
        deepseek_key_file = 'runtime\deepseek-key.dpapi'
        dashboard_port   = 6185
        napcat_port      = 6099
        qq_port          = 6199
    }
    $path = Join-Path $script:JingyuRoot 'config.json'
    if (Test-Path -LiteralPath $path) {
        try {
            $user = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $user.PSObject.Properties) {
                if ($null -ne $p.Value -and "$($p.Value)" -ne '') { $cfg[$p.Name] = $p.Value }
            }
        } catch {
            Write-Warning "config.json 解析失败，使用默认配置：$($_.Exception.Message)"
        }
    }
    $script:JingyuConfig = [pscustomobject]$cfg
    return $script:JingyuConfig
}

function Resolve-JingyuPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    if ([IO.Path]::IsPathRooted($Path)) { return $Path }
    return (Join-Path $script:JingyuRoot $Path)
}
