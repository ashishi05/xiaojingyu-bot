param([ValidateSet('core','personal')][string]$Service)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')
$deploy=Get-JingyuConfig
$env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'
try {
    if($Service -eq 'core'){
        $secretPath=Resolve-JingyuPath $deploy.deepseek_key_file
        if($secretPath -and (Test-Path -LiteralPath $secretPath)){
            $secret=Get-Content -LiteralPath $secretPath -Raw | ConvertTo-SecureString
            $env:DEEPSEEK_API_KEY=[Net.NetworkCredential]::new('',$secret).Password
        }
        $file=Resolve-JingyuPath $deploy.python;$serviceArgs=@('main.py');$dir=Resolve-JingyuPath $deploy.astrbot_dir
    }else{
        $password=Join-Path $PSScriptRoot 'runtime/qq-password.dpapi'
        if(Test-Path -LiteralPath $password){$secret=Get-Content -LiteralPath $password -Raw | ConvertTo-SecureString;$env:NAPCAT_QUICK_PASSWORD=[Net.NetworkCredential]::new('',$secret).Password}
        if([string]$deploy.qq -notmatch '^\d{5,12}$' -or [string]$deploy.qq -eq '10003'){throw '请先在本机 config.json 配置自己的 QQ 号'}
        $dir=Resolve-JingyuPath $deploy.napcat_dir;$file=Join-Path $dir 'node.exe';$serviceArgs=@('index.js','-q',[string]$deploy.qq)
    }
    $stamp=Get-Date -Format yyyyMMdd-HHmmss
    Start-Process -FilePath $file -ArgumentList $serviceArgs -WorkingDirectory $dir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot "logs/launcher-$Service-$stamp.out.log") -RedirectStandardError (Join-Path $PSScriptRoot "logs/launcher-$Service-$stamp.err.log") | Out-Null
}finally{
    Remove-Item Env:DEEPSEEK_API_KEY,Env:NAPCAT_QUICK_PASSWORD -ErrorAction SilentlyContinue
}
