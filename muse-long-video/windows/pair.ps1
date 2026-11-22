$ErrorActionPreference='Stop'
$dir=$PSScriptRoot
$cfg=Get-Content -Raw -Encoding UTF8 -LiteralPath "$dir\studio\settings.local.json"|ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
$f=New-Object Windows.Forms.OpenFileDialog
$f.Filter='SynMewInfiniteCanvas.exe|SynMewInfiniteCanvas.exe'
if($f.ShowDialog() -ne 'OK'){exit}
$port=Read-Host '输入星幕本机配对端口'
& "$dir\runtime\python.exe" (Join-Path $cfg.skill "scripts\setup_synmew.py") --config (Join-Path $cfg.codex config.toml) --workspace $cfg.workspace --exe $f.FileName --port $port --apply --probe --pair-only
if($LASTEXITCODE){throw '星幕配对未完成，请打开星幕并核对自己的端口和配对信息。'}
& "$dir\runtime\python.exe" -B -c "from settings_io import merge_settings; import sys; merge_settings(sys.argv[1],{'starcanvas':True})" "$dir\studio\settings.local.json"
if($LASTEXITCODE){throw '星幕连接已配好，但工作台设置写入失败。'}
Write-Host '配对完成。请重新打开工作台服务。'